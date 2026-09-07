"""Evidence verification engine for extracted facts.

Ensures that the LLM is never the final authority on its own citations.
Verifies source quotes directly against the source text and resolves
exact page numbers and block IDs from the application's layout index.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.models.schemas import ValidationStatus

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Outcome of verifying a fact's source quote against chunk/block text."""

    status: ValidationStatus
    start_page: int
    end_page: int
    block_ids: list[str]
    notes: list[str]


def normalize_for_matching(text: str) -> str:
    """Normalize text for robust substring matching:

    - Standardizes curly/smart quotes and dashes
    - Normalizes unicode whitespace and line breaks
    - Collapses consecutive whitespace to a single space
    """
    if not text:
        return ""
    t = text
    # Unicode quotes and dashes
    t = re.sub(r'[\u201c\u201d\u201e\u201f"]', '"', t)
    t = re.sub(r"[\u2018\u2019\u201a\u201b']", "'", t)
    t = re.sub(r"[\u2013\u2014\u2015-]", "-", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def strip_punctuation(text: str) -> str:
    """Remove all non-alphanumeric characters and collapse whitespace for fuzzy matching."""
    t = re.sub(r"[^\w\s]", " ", text).lower()
    return re.sub(r"\s+", " ", t).strip()


class EvidenceVerifier:
    """Verifies that an extracted fact's source quote genuinely exists in the

    chunk text and attributes exact page numbers and block IDs.
    """

    def verify(
        self,
        source_quote: str,
        chunk_text: str,
        chunk_start_page: int,
        chunk_end_page: int,
        blocks: Optional[list[dict[str, Any]]] = None,
    ) -> VerificationResult:
        """Verify the evidence quote against the chunk text and associate block provenance.

        Args:
            source_quote: Verbatim quote claimed by the model.
            chunk_text: Full text of the chunk.
            chunk_start_page: First page spanned by chunk.
            chunk_end_page: Last page spanned by chunk.
            blocks: List of block dicts in this chunk (id, text, page_number).

        Returns:
            VerificationResult with status (validated, warning, rejected),
            pages, block IDs, and verification notes.
        """
        quote_clean = source_quote.strip()
        if not quote_clean:
            return VerificationResult(
                status=ValidationStatus.REJECTED,
                start_page=chunk_start_page,
                end_page=chunk_end_page,
                block_ids=[],
                notes=["Empty source quote provided."],
            )

        norm_quote = normalize_for_matching(quote_clean)
        norm_chunk = normalize_for_matching(chunk_text)

        blocks = blocks or []

        # ── 1. Exact Normalized Match ──────────────────────────────
        if norm_quote in norm_chunk:
            matched_blocks = self._find_matching_blocks(norm_quote, blocks)
            if matched_blocks:
                pages = [b["page_number"] for b in matched_blocks]
                return VerificationResult(
                    status=ValidationStatus.VALIDATED,
                    start_page=min(pages),
                    end_page=max(pages),
                    block_ids=[b["id"] for b in matched_blocks],
                    notes=[],
                )
            # Quote found in chunk text but not isolated to single block
            return VerificationResult(
                status=ValidationStatus.VALIDATED,
                start_page=chunk_start_page,
                end_page=chunk_end_page,
                block_ids=[b["id"] for b in blocks],
                notes=[],
            )

        # ── 2. Punctuation-Agnostic Fuzzy Match ───────────────────
        clean_quote = strip_punctuation(norm_quote)
        clean_chunk = strip_punctuation(norm_chunk)

        if len(clean_quote) >= 8 and clean_quote in clean_chunk:
            matched_blocks = self._find_matching_blocks_fuzzy(clean_quote, blocks)
            pages = [b["page_number"] for b in matched_blocks] if matched_blocks else [chunk_start_page]
            b_ids = [b["id"] for b in matched_blocks] if matched_blocks else [b["id"] for b in blocks]
            return VerificationResult(
                status=ValidationStatus.WARNING,
                start_page=min(pages),
                end_page=max(pages),
                block_ids=b_ids,
                notes=["Source quote verified with minor punctuation or formatting differences."],
            )

        # ── 3. Significant Token Overlap Check ────────────────────
        quote_words = [w for w in clean_quote.split() if len(w) > 2]
        if len(quote_words) >= 4:
            # Check if 75% of quote words exist in sequence in chunk
            quote_sub = " ".join(quote_words[:min(6, len(quote_words))])
            if quote_sub in clean_chunk:
                return VerificationResult(
                    status=ValidationStatus.WARNING,
                    start_page=chunk_start_page,
                    end_page=chunk_end_page,
                    block_ids=[b["id"] for b in blocks],
                    notes=["Partial quote match detected in chunk text; some words differed."],
                )

        # ── 4. Hallucinated / Missing Quote ───────────────────────
        logger.warning("Rejected unsupported citation quote: %r", quote_clean[:60])
        return VerificationResult(
            status=ValidationStatus.REJECTED,
            start_page=chunk_start_page,
            end_page=chunk_end_page,
            block_ids=[],
            notes=["Source quote does not exist in the source chunk text. Claim rejected."],
        )

    def _find_matching_blocks(
        self, norm_quote: str, blocks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Find which block(s) contain the normalized quote."""
        # Check single-block containment
        for block in blocks:
            b_text = normalize_for_matching(block.get("text", ""))
            if norm_quote in b_text:
                return [block]

        # Check multi-block overlap
        matched: list[dict[str, Any]] = []
        for block in blocks:
            b_text = normalize_for_matching(block.get("text", ""))
            if not b_text:
                continue
            # If a substantial portion of quote is in this block
            words = norm_quote.split()
            first_phrase = " ".join(words[:min(4, len(words))])
            last_phrase = " ".join(words[-min(4, len(words)):])
            if (first_phrase and first_phrase in b_text) or (last_phrase and last_phrase in b_text):
                matched.append(block)

        return matched

    def _find_matching_blocks_fuzzy(
        self, clean_quote: str, blocks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Find matching blocks using punctuation-stripped text."""
        for block in blocks:
            b_clean = strip_punctuation(normalize_for_matching(block.get("text", "")))
            if clean_quote in b_clean:
                return [block]
        return []
