"""Fact extraction service orchestrating structured LLM calls,

evidence verification, caching, and database persistence.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import sqlite3
import uuid
from typing import Any, Callable, Optional

from app.config import get_settings
from app.db.database import get_connection
from app.models.schemas import ChunkSchema, ChunkStatus, FactSchema, ValidationStatus, ValueType
from app.services.extraction.models import ExtractedFact, ExtractionResult, PromptVersion
from app.services.extraction.prompts import build_extraction_messages
from app.services.extraction.verifier import EvidenceVerifier, VerificationResult

logger = logging.getLogger(__name__)

OPERATION_NAME = "fact_extraction"


class BaseExtractionProvider(abc.ABC):
    """Abstract interface for LLM extraction backends."""

    @abc.abstractmethod
    async def generate_facts(
        self, messages: list[dict[str, str]], model: str
    ) -> ExtractionResult:
        """Call LLM and return structured ExtractionResult."""
        ...


class OpenAIExtractionProvider(BaseExtractionProvider):
    """Production provider using OpenAI Python SDK and structured outputs."""

    def __init__(self, api_key: Optional[str] = None):
        import openai

        settings = get_settings()
        key = api_key or settings.effective_api_key
        base_url = settings.resolved_base_url
        self.client = openai.AsyncOpenAI(api_key=key, base_url=base_url)

    async def generate_facts(
        self, messages: list[dict[str, str]], model: str
    ) -> ExtractionResult:
        """Invoke client.beta.chat.completions.parse with ExtractionResult schema."""
        completion = await self.client.beta.chat.completions.parse(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            response_format=ExtractionResult,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI model returned empty structured output")
        return parsed


class MockExtractionProvider(BaseExtractionProvider):
    """Mock provider for unit and integration testing without an API key."""

    def __init__(
        self,
        mock_result: Optional[ExtractionResult] = None,
        handler: Optional[Callable[[list[dict[str, str]], str], ExtractionResult]] = None,
    ):
        self.mock_result = mock_result
        self.handler = handler
        self.call_count = 0
        self.last_messages: Optional[list[dict[str, str]]] = None

    async def generate_facts(
        self, messages: list[dict[str, str]], model: str
    ) -> ExtractionResult:
        self.call_count += 1
        self.last_messages = messages

        if self.handler:
            return self.handler(messages, model)
        if self.mock_result is not None:
            return self.mock_result

        # Default fallback mock: extract simple facts based on message text
        user_msg = messages[-1]["content"] if messages else ""
        facts: list[ExtractedFact] = []

        # Look for dollar amounts like $120 million or $65M
        import re
        money_matches = re.finditer(r"(\$?\d+(?:\.\d+)?\s*(?:million|billion|M|B)?)\b", user_msg)
        for m in money_matches:
            val_str = m.group(1).strip()
            if len(val_str) > 1:
                # Find line containing this match as source quote
                for line in user_msg.split("\n"):
                    if val_str in line and not line.startswith("Document Text:"):
                        facts.append(
                            ExtractedFact(
                                source_quote=line.strip()[:150],
                                subject="Organization",
                                subject_mention="Company",
                                predicate="financial_metric",
                                predicate_mention="metric",
                                value_text=val_str,
                                value_type=ValueType.CURRENCY if "$" in val_str else ValueType.NUMBER,
                                confidence=0.95,
                            )
                        )
                        break

        return ExtractionResult(facts=facts, extraction_notes=["Mock extraction performed."])


class ExtractionService:
    """Coordinates the full structured fact extraction pipeline:

    - Bounded concurrency with asyncio.Semaphore
    - Transient retry logic with exponential backoff
    - SQLite llm_cache tier
    - Python evidence verification (exact block and page grounding)
    - Full SQLite persistence of facts with provenance
    """

    def __init__(
        self,
        provider: Optional[BaseExtractionProvider] = None,
        prompt_version: str = PromptVersion.V1.value,
        max_concurrency: Optional[int] = None,
    ):
        settings = get_settings()
        if provider is not None:
            self.provider = provider
        elif settings.effective_api_key and not settings.effective_api_key.startswith("sk-test-"):
            self.provider = OpenAIExtractionProvider()
        else:
            self.provider = MockExtractionProvider()

        self.prompt_version = prompt_version
        self.model = settings.resolved_extraction_model
        concurrency = max_concurrency or settings.resolved_max_llm_concurrency
        self.semaphore = asyncio.Semaphore(concurrency)
        self.verifier = EvidenceVerifier()

    async def extract_document(
        self, document_id: str, force: bool = False
    ) -> list[FactSchema]:
        """Extract facts across all chunks of a document concurrently.

        Args:
            document_id: Target document ID.
            force: If True, re-extract even if facts already exist.

        Returns:
            List of created and verified FactSchema records.
        """
        conn = get_connection()
        try:
            # Check existing facts
            if not force:
                existing_facts = conn.execute(
                    "SELECT * FROM facts WHERE document_id = ?", (document_id,)
                ).fetchall()
                if existing_facts:
                    logger.info(
                        "Returning %d existing facts for document %s",
                        len(existing_facts),
                        document_id,
                    )
                    return [self._row_to_fact_schema(r) for r in existing_facts]

            # Fetch chunks for this document
            chunk_rows = conn.execute(
                """SELECT * FROM chunks WHERE document_id = ?
                   ORDER BY sequence_index ASC""",
                (document_id,),
            ).fetchall()

            if not chunk_rows:
                logger.warning("No chunks found for document %s", document_id)
                return []

            chunks = [
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
                for r in chunk_rows
            ]

            # Fetch all blocks for this document for block-level grounding
            block_rows = conn.execute(
                """SELECT b.id, b.text, p.page_number FROM blocks b
                   JOIN pages p ON b.page_id = p.id
                   WHERE p.document_id = ?""",
                (document_id,),
            ).fetchall()
            doc_blocks = [dict(r) for r in block_rows]
        finally:
            conn.close()

        # Execute extraction for all chunks with bounded concurrency
        tasks = [self.extract_chunk(chunk, doc_blocks) for chunk in chunks]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        all_facts: list[FactSchema] = []
        for fact_list in results:
            all_facts.extend(fact_list)

        # Persist extracted facts to database
        self._persist_facts(document_id, all_facts, [c.id for c in chunks])
        logger.info(
            "Extracted and persisted %d facts for document %s",
            len(all_facts),
            document_id,
        )
        return all_facts

    async def extract_chunk(
        self,
        chunk: ChunkSchema,
        doc_blocks: Optional[list[dict[str, Any]]] = None,
    ) -> list[FactSchema]:
        """Process a single chunk: check cache, call LLM with retry, verify citations."""
        chunk_hash = chunk.content_hash or ""
        heading_path = json.loads(chunk.heading_path_json) if chunk.heading_path_json else []

        # ── 1. Check SQLite LLM Cache ──────────────────────────────
        cached_result = self._get_cached(chunk_hash)
        if cached_result is not None:
            logger.info("Cache hit for chunk %s (hash=%s)", chunk.id[:8], chunk_hash[:10])
            extraction_result = cached_result
        else:
            # ── 2. Call LLM with bounded concurrency and retry ─────
            messages = build_extraction_messages(chunk.text, heading_path)
            extraction_result = await self._call_with_retry(messages)
            # Store in cache
            self._set_cached(chunk_hash, extraction_result)

        # ── 3. Evidence Verification & Provenance Grounding ────────
        # Filter blocks specifically belonging to this chunk
        chunk_block_ids = set(json.loads(chunk.block_ids_json) if chunk.block_ids_json else [])
        chunk_blocks = (
            [b for b in doc_blocks if b["id"] in chunk_block_ids]
            if doc_blocks
            else []
        )

        facts: list[FactSchema] = []
        for ef in extraction_result.facts:
            # Verify quote against chunk text and match block IDs
            verif: VerificationResult = self.verifier.verify(
                source_quote=ef.source_quote,
                chunk_text=chunk.text,
                chunk_start_page=chunk.start_page,
                chunk_end_page=chunk.end_page,
                blocks=chunk_blocks,
            )

            notes = list(verif.notes)
            if ef.notes:
                notes.append(ef.notes)

            fact = FactSchema(
                id=str(uuid.uuid4()),
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                subject=ef.subject,
                subject_mention=ef.subject_mention,
                predicate=ef.predicate,
                predicate_mention=ef.predicate_mention,
                value_text=ef.value_text,
                value_type=ef.value_type,
                numeric_value=ef.numeric_value,
                unit=ef.unit,
                currency=ef.currency,
                time_text=ef.time_text,
                scope=ef.scope,
                geography=ef.geography,
                qualifiers_json=json.dumps(ef.qualifiers),
                source_quote=ef.source_quote,
                source_page_start=verif.start_page,
                source_page_end=verif.end_page,
                source_block_ids_json=json.dumps(verif.block_ids),
                extraction_confidence=ef.confidence,
                validation_status=verif.status,
                extraction_notes_json=json.dumps(notes),
            )
            facts.append(fact)

        return facts

    async def _call_with_retry(
        self,
        messages: list[dict[str, str]],
        max_retries: int = 3,
        initial_delay: float = 0.5,
        backoff_factor: float = 2.0,
    ) -> ExtractionResult:
        """Execute LLM call within semaphore with exponential backoff on transient errors."""
        last_exc = None
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                async with self.semaphore:
                    if get_settings().is_gemini:
                        await asyncio.sleep(4.5)  # ~13 RPM, under 15 RPM free-tier limit
                    return await self.provider.generate_facts(messages, self.model)
            except Exception as exc:
                last_exc = exc
                err_name = type(exc).__name__
                # If authentication or bad request error, don't retry fruitlessly
                if "Authentication" in err_name or "BadRequest" in err_name:
                    logger.error("Fatal LLM error: %s", exc)
                    raise

                is_rate_limit = (
                    "RateLimit" in err_name
                    or "429" in str(exc)
                    or "RESOURCE_EXHAUSTED" in str(exc)
                )
                from app.core.rate_limiting import extract_retry_delay

                if is_rate_limit and get_settings().is_gemini:
                    retry_wait = extract_retry_delay(exc, default=45.0)
                else:
                    retry_wait = max(delay, 5.0 * (attempt + 1)) if is_rate_limit else delay
                logger.warning(
                    "LLM call transient failure (%s, attempt %d/%d): %s. Retrying in %.2fs...",
                    err_name,
                    attempt + 1,
                    max_retries,
                    exc,
                    retry_wait,
                )
                await asyncio.sleep(retry_wait)
                delay *= backoff_factor

        logger.error("LLM call failed after %d attempts: %s", max_retries, last_exc)
        raise last_exc  # type: ignore[misc]

    def _get_cached(self, chunk_hash: str) -> Optional[ExtractionResult]:
        """Check the llm_cache table."""
        if not chunk_hash:
            return None
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT response_json FROM llm_cache
                   WHERE operation = ? AND model = ? AND prompt_version = ? AND input_hash = ?""",
                (OPERATION_NAME, self.model, self.prompt_version, chunk_hash),
            ).fetchone()
            if row:
                return ExtractionResult.model_validate_json(row["response_json"])
            return None
        finally:
            conn.close()

    def _set_cached(self, chunk_hash: str, result: ExtractionResult) -> None:
        """Write extraction result to llm_cache table."""
        if not chunk_hash:
            return
        conn = get_connection()
        try:
            cache_id = str(uuid.uuid4())
            conn.execute(
                """INSERT OR REPLACE INTO llm_cache
                   (id, operation, model, prompt_version, input_hash, response_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    cache_id,
                    OPERATION_NAME,
                    self.model,
                    self.prompt_version,
                    chunk_hash,
                    result.model_dump_json(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _persist_facts(
        self, document_id: str, facts: list[FactSchema], chunk_ids: list[str]
    ) -> None:
        """Persist facts and update chunk status inside a single transaction."""
        conn = get_connection()
        try:
            # Clear previous facts for this document
            conn.execute("DELETE FROM facts WHERE document_id = ?", (document_id,))

            for f in facts:
                conn.execute(
                    """INSERT INTO facts (
                        id, document_id, chunk_id, subject, subject_mention,
                        entity_id, predicate, predicate_mention, value_text,
                        value_type, numeric_value, normalized_numeric_value,
                        unit, normalized_unit, currency, time_text, time_start,
                        time_end, time_granularity, scope, geography,
                        qualifiers_json, source_quote, source_page_start,
                        source_page_end, source_block_ids_json,
                        extraction_confidence, validation_status, extraction_notes_json
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )""",
                    (
                        f.id,
                        f.document_id,
                        f.chunk_id,
                        f.subject,
                        f.subject_mention,
                        f.entity_id,
                        f.predicate,
                        f.predicate_mention,
                        f.value_text,
                        f.value_type.value,
                        f.numeric_value,
                        f.normalized_numeric_value,
                        f.unit,
                        f.normalized_unit,
                        f.currency,
                        f.time_text,
                        f.time_start,
                        f.time_end,
                        f.time_granularity.value if f.time_granularity else None,
                        f.scope,
                        f.geography,
                        f.qualifiers_json,
                        f.source_quote,
                        f.source_page_start,
                        f.source_page_end,
                        f.source_block_ids_json,
                        f.extraction_confidence,
                        f.validation_status.value,
                        f.extraction_notes_json,
                    ),
                )

            # Mark chunks as completed
            if chunk_ids:
                placeholders = ",".join("?" * len(chunk_ids))
                conn.execute(
                    f"UPDATE chunks SET extraction_status = 'completed' WHERE id IN ({placeholders})",
                    chunk_ids,
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _row_to_fact_schema(row: sqlite3.Row) -> FactSchema:
        return FactSchema(
            id=row["id"],
            document_id=row["document_id"],
            chunk_id=row["chunk_id"],
            subject=row["subject"],
            subject_mention=row["subject_mention"],
            entity_id=row["entity_id"],
            predicate=row["predicate"],
            predicate_mention=row["predicate_mention"],
            value_text=row["value_text"],
            value_type=ValueType(row["value_type"]),
            numeric_value=row["numeric_value"],
            normalized_numeric_value=row["normalized_numeric_value"],
            unit=row["unit"],
            normalized_unit=row["normalized_unit"],
            currency=row["currency"],
            time_text=row["time_text"],
            time_start=row["time_start"],
            time_end=row["time_end"],
            time_granularity=row["time_granularity"],
            scope=row["scope"],
            geography=row["geography"],
            qualifiers_json=row["qualifiers_json"],
            source_quote=row["source_quote"],
            source_page_start=row["source_page_start"],
            source_page_end=row["source_page_end"],
            source_block_ids_json=row["source_block_ids_json"],
            extraction_confidence=row["extraction_confidence"],
            validation_status=ValidationStatus(row["validation_status"]),
            extraction_notes_json=row["extraction_notes_json"],
        )
