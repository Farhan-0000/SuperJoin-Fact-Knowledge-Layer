"""Layout-aware, page-aware chunking service.

Partitions PDF document blocks into semantic chunks using headings,
paragraphs, table blocks, natural section boundaries, and token budgets.

Adheres strictly to the provenance rule:
A fact extracted from a chunk may only cite source blocks that belong
to that chunk (enforced via explicit block_ids tracking).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from app.db.database import get_connection
from app.models.schemas import ChunkSchema, ChunkStatus
from app.services.ingestion.tokenizer import count_tokens

logger = logging.getLogger(__name__)

# Deterministic namespace for chunk UUID generation
CHUNK_NAMESPACE = uuid.UUID("e7b4a2c1-8f3e-4d5a-9b6c-1e2f3a4b5c6d")

# Token targets
DEFAULT_MIN_TOKENS = 800
DEFAULT_MAX_TOKENS = 2500
DEFAULT_OVERLAP_TOKENS = 150


@dataclass
class BlockRecord:
    """Internal representation of a layout block for chunking."""

    id: str
    page_id: str
    page_number: int
    block_index: int
    block_type: str
    text: str
    reading_order: int
    token_count: int = 0
    metadata_json: Optional[str] = None

    def __post_init__(self):
        if not self.token_count and self.text:
            self.token_count = count_tokens(self.text)


def _compute_deterministic_chunk_id(document_id: str, sequence_index: int) -> str:
    """Generate a deterministic UUID for a chunk based on document_id and sequence_index."""
    seed = f"{document_id}_chunk_{sequence_index}"
    return str(uuid.uuid5(CHUNK_NAMESPACE, seed))


def _compute_chunk_content_hash(
    text: str, heading_path: list[str], block_ids: list[str]
) -> str:
    """Compute a deterministic SHA-256 hash of the chunk content and provenance."""
    hasher = hashlib.sha256()
    hasher.update(text.strip().encode("utf-8"))
    for h in heading_path:
        hasher.update(h.strip().encode("utf-8"))
    for bid in block_ids:
        hasher.update(bid.encode("utf-8"))
    return hasher.hexdigest()


class LayoutAwareChunker:
    """Generates semantic, layout-aware chunks from document blocks.

    Features:
    - Never chunks by fixed page count alone.
    - Honors section boundaries defined by headings.
    - Keeps table blocks intact to prevent semantic destruction.
    - Allows smaller chunks for naturally short sections and larger chunks
      when splitting tables/paragraphs would destroy context.
    - Adds contextual overlap between neighboring chunks while tracking
      all block IDs for strict provenance validation.
    """

    def __init__(
        self,
        min_tokens: int = DEFAULT_MIN_TOKENS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    ):
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def chunk_document(
        self, document_id: str, force: bool = False
    ) -> list[ChunkSchema]:
        """Load document blocks from SQLite, produce layout-aware chunks,

        and persist them to the database.

        Args:
            document_id: Target document ID.
            force: If True, delete and recreate existing chunks.

        Returns:
            List of created ChunkSchema objects.
        """
        conn = get_connection()
        try:
            # 1. Check existing chunks
            if not force:
                existing = conn.execute(
                    "SELECT * FROM chunks WHERE document_id = ? ORDER BY sequence_index ASC",
                    (document_id,),
                ).fetchall()
                if existing:
                    logger.info(
                        "Returning %d existing chunks for doc %s",
                        len(existing),
                        document_id,
                    )
                    return [
                        ChunkSchema(
                            id=r["id"],
                            document_id=r["document_id"],
                            sequence_index=r["sequence_index"],
                            start_page=r["start_page"],
                            end_page=r["end_page"],
                            block_ids_json=r["block_ids_json"],
                            heading_path_json=r["heading_path_json"],
                            text=r["text"],
                            token_count=r["token_count"],
                            previous_chunk_id=r["previous_chunk_id"],
                            next_chunk_id=r["next_chunk_id"],
                            has_table=bool(r["has_table"]),
                            has_low_quality_page=bool(r["has_low_quality_page"]),
                            content_hash=r["content_hash"],
                            extraction_status=ChunkStatus(r["extraction_status"]),
                        )
                        for r in existing
                    ]

            # 2. Query blocks with page information
            block_rows = conn.execute(
                """SELECT b.id, b.page_id, p.page_number, b.block_index,
                          b.block_type, b.text, b.reading_order, b.metadata_json,
                          p.is_scanned, p.text_quality
                   FROM blocks b
                   JOIN pages p ON b.page_id = p.id
                   WHERE p.document_id = ?
                   ORDER BY p.page_number ASC, b.reading_order ASC, b.block_index ASC""",
                (document_id,),
            ).fetchall()

            if not block_rows:
                logger.warning("No blocks found for document %s", document_id)
                return []

            # Page quality map: page_number -> has_low_quality
            page_quality_map: dict[int, bool] = {}
            blocks: list[BlockRecord] = []
            for r in block_rows:
                page_num = r["page_number"]
                is_scanned = bool(r["is_scanned"])
                text_qual = r["text_quality"]
                is_low_quality = is_scanned or (text_qual is not None and text_qual < 0.5)
                page_quality_map[page_num] = is_low_quality

                blocks.append(
                    BlockRecord(
                        id=r["id"],
                        page_id=r["page_id"],
                        page_number=page_num,
                        block_index=r["block_index"],
                        block_type=r["block_type"],
                        text=r["text"],
                        reading_order=r["reading_order"],
                        metadata_json=r["metadata_json"],
                    )
                )

            # 3. Generate chunks
            chunks = self.create_chunks_from_blocks(
                document_id=document_id,
                blocks=blocks,
                page_quality_map=page_quality_map,
            )

            # 4. Persist to DB
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            for c in chunks:
                conn.execute(
                    """INSERT INTO chunks (
                        id, document_id, sequence_index, start_page, end_page,
                        block_ids_json, heading_path_json, text, token_count,
                        previous_chunk_id, next_chunk_id, has_table,
                        has_low_quality_page, content_hash, extraction_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        c.id,
                        c.document_id,
                        c.sequence_index,
                        c.start_page,
                        c.end_page,
                        c.block_ids_json,
                        c.heading_path_json,
                        c.text,
                        c.token_count,
                        c.previous_chunk_id,
                        c.next_chunk_id,
                        1 if c.has_table else 0,
                        1 if c.has_low_quality_page else 0,
                        c.content_hash,
                        c.extraction_status.value,
                    ),
                )
            conn.commit()
            logger.info("Persisted %d chunks for document %s", len(chunks), document_id)
            return chunks
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_chunks_from_blocks(
        self,
        document_id: str,
        blocks: list[BlockRecord],
        page_quality_map: Optional[dict[int, bool]] = None,
    ) -> list[ChunkSchema]:
        """Pure chunk generation algorithm given a list of blocks."""
        if not blocks:
            return []

        page_quality_map = page_quality_map or {}

        # ── Step A: Group blocks into section groups ────────────────
        # A section group is a list of primary blocks belonging to a logical unit
        groups: list[dict[str, Any]] = []
        current_group_blocks: list[BlockRecord] = []
        current_tokens = 0
        current_heading_path: list[str] = []

        for block in blocks:
            # Skip empty blocks or pure whitespace
            if not block.text.strip():
                continue

            b_tokens = block.token_count

            # Update heading hierarchy if block is a heading
            is_heading = block.block_type == "heading"
            if is_heading:
                current_heading_path = self._update_heading_path(
                    current_heading_path, block.text.strip()
                )

            # Check for section break at heading
            if is_heading and current_group_blocks:
                # If current group has reached minimum token threshold, finalize group
                if current_tokens >= self.min_tokens:
                    groups.append({
                        "blocks": current_group_blocks,
                        "heading_path": list(current_heading_path),
                        "tokens": current_tokens,
                    })
                    current_group_blocks = [block]
                    current_tokens = b_tokens
                    continue

            # Check if block is a table
            is_table = block.block_type == "table"
            if is_table and current_group_blocks:
                # If adding table exceeds max tokens and we already have min tokens, start new group
                if (current_tokens + b_tokens > self.max_tokens) and (current_tokens >= self.min_tokens):
                    groups.append({
                        "blocks": current_group_blocks,
                        "heading_path": list(current_heading_path),
                        "tokens": current_tokens,
                    })
                    current_group_blocks = [block]
                    current_tokens = b_tokens
                    continue

            # Check token ceiling for normal paragraphs
            if (current_tokens + b_tokens > self.max_tokens) and (current_tokens >= self.min_tokens):
                groups.append({
                    "blocks": current_group_blocks,
                    "heading_path": list(current_heading_path),
                    "tokens": current_tokens,
                })
                current_group_blocks = [block]
                current_tokens = b_tokens
            else:
                current_group_blocks.append(block)
                current_tokens += b_tokens

        # Append trailing blocks
        if current_group_blocks:
            groups.append({
                "blocks": current_group_blocks,
                "heading_path": list(current_heading_path),
                "tokens": current_tokens,
            })

        # ── Step B: Assemble chunks with contextual overlap ─────────
        raw_chunks: list[dict[str, Any]] = []

        for idx, group in enumerate(groups):
            primary_blocks: list[BlockRecord] = group["blocks"]
            heading_path: list[str] = group["heading_path"]

            # Compute contextual overlap from the previous group's tail
            overlap_blocks: list[BlockRecord] = []
            if idx > 0 and self.overlap_tokens > 0:
                prev_primary = groups[idx - 1]["blocks"]
                accumulated_overlap_tokens = 0
                # Take blocks from the end of previous group backwards up to overlap_tokens
                for pb in reversed(prev_primary):
                    # Don't take an isolated heading as overlap
                    if pb.block_type == "heading" and not overlap_blocks:
                        continue
                    overlap_blocks.insert(0, pb)
                    accumulated_overlap_tokens += pb.token_count
                    if accumulated_overlap_tokens >= self.overlap_tokens or len(overlap_blocks) >= 2:
                        break

            # Combine overlap and primary blocks
            # All blocks in all_blocks are officially part of this chunk's block_ids
            # so the provenance rule is strictly satisfied.
            all_blocks: list[BlockRecord] = overlap_blocks + primary_blocks
            block_ids = [b.id for b in all_blocks]

            # Build chunk text
            text_parts: list[str] = []
            if overlap_blocks:
                overlap_text = "\n\n".join(b.text.strip() for b in overlap_blocks if b.text.strip())
                text_parts.append(f"[Context from previous section]:\n{overlap_text}\n---")

            for pb in primary_blocks:
                t = pb.text.strip()
                if t:
                    text_parts.append(t)

            chunk_text = "\n\n".join(text_parts)
            chunk_tokens = count_tokens(chunk_text)

            # Determine page boundaries (spanned by all blocks in chunk)
            start_page = min(b.page_number for b in all_blocks)
            end_page = max(b.page_number for b in all_blocks)

            has_table = any(b.block_type == "table" for b in all_blocks)
            has_low_quality = any(
                page_quality_map.get(p, False) for p in range(start_page, end_page + 1)
            )

            content_hash = _compute_chunk_content_hash(chunk_text, heading_path, block_ids)

            raw_chunks.append({
                "sequence_index": idx,
                "start_page": start_page,
                "end_page": end_page,
                "block_ids": block_ids,
                "heading_path": heading_path,
                "text": chunk_text,
                "token_count": chunk_tokens,
                "has_table": has_table,
                "has_low_quality_page": has_low_quality,
                "content_hash": content_hash,
            })

        # ── Step C: Link previous/next IDs and assign deterministic IDs ──
        total_chunks = len(raw_chunks)
        chunk_ids = [
            _compute_deterministic_chunk_id(document_id, i) for i in range(total_chunks)
        ]

        final_chunks: list[ChunkSchema] = []
        for i, rc in enumerate(raw_chunks):
            cid = chunk_ids[i]
            prev_id = chunk_ids[i - 1] if i > 0 else None
            next_id = chunk_ids[i + 1] if i < total_chunks - 1 else None

            final_chunks.append(
                ChunkSchema(
                    id=cid,
                    document_id=document_id,
                    sequence_index=rc["sequence_index"],
                    start_page=rc["start_page"],
                    end_page=rc["end_page"],
                    block_ids_json=json.dumps(rc["block_ids"]),
                    heading_path_json=json.dumps(rc["heading_path"]),
                    text=rc["text"],
                    token_count=rc["token_count"],
                    previous_chunk_id=prev_id,
                    next_chunk_id=next_id,
                    has_table=rc["has_table"],
                    has_low_quality_page=rc["has_low_quality_page"],
                    content_hash=rc["content_hash"],
                    extraction_status=ChunkStatus.PENDING,
                )
            )

        return final_chunks

    def _update_heading_path(
        self, current_path: list[str], heading_text: str
    ) -> list[str]:
        """Update heading hierarchy using section numbers and indentation patterns."""
        clean_text = re.sub(r"\s+", " ", heading_text).strip()
        if not clean_text:
            return current_path

        # Match numbered headings like "1.", "1.2", "1.2.3"
        num_match = re.match(r"^(\d+(?:\.\d+)*)", clean_text)
        if num_match:
            parts = num_match.group(1).split(".")
            level = len(parts)
            # Truncate path to level - 1 and append
            new_path = current_path[: level - 1]
            new_path.append(clean_text)
            return new_path

        # Check for top-level keywords
        if re.match(r"^(?:chapter|part|section)\s+\d+", clean_text, re.IGNORECASE):
            return [clean_text]

        # By default, treat as a single active heading or sub-heading
        if not current_path:
            return [clean_text]
        if len(current_path) == 1:
            return [current_path[0], clean_text]
        return [current_path[0], clean_text]
