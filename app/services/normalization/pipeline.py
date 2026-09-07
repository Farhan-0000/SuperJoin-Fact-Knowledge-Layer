"""Normalization pipeline unifying numeric, temporal, predicate, and entity resolution,

followed by same-document deduplication.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.db.database import get_connection
from app.models.schemas import FactSchema, ValidationStatus, ValueType
from app.services.normalization.dates import normalize_date_period
from app.services.normalization.deduplication import deduplicate_facts
from app.services.normalization.entities import EntityResolver
from app.services.normalization.numeric import normalize_numeric
from app.services.normalization.predicates import normalize_predicate

logger = logging.getLogger(__name__)


class NormalizationPipeline:
    """Orchestrates deterministic value normalization, canonical entity resolution,

    predicate standardization, and same-document deduplication.
    """

    def __init__(self):
        self.entity_resolver = EntityResolver()

    def normalize_fact(
        self,
        fact: FactSchema,
        document_context: Optional[dict] = None,
    ) -> FactSchema:
        """Apply deterministic normalization to a single fact."""
        # ── 1. Numeric Normalization ───────────────────────────────
        num_res = normalize_numeric(
            value_text=fact.value_text,
            declared_unit=fact.unit,
            declared_currency=fact.currency,
            declared_type=fact.value_type,
        )

        # ── 2. Date & Period Normalization ─────────────────────────
        date_res = normalize_date_period(
            time_text=fact.time_text,
            document_context=document_context,
        )

        # ── 3. Predicate Normalization ─────────────────────────────
        pred_res = normalize_predicate(fact.predicate)

        # ── 4. Entity Resolution ───────────────────────────────────
        entity_res = self.entity_resolver.resolve_entity(
            name=fact.subject,
            mention_text=fact.subject_mention,
        )

        return FactSchema(
            id=fact.id,
            document_id=fact.document_id,
            chunk_id=fact.chunk_id,
            subject=fact.subject,
            subject_mention=fact.subject_mention,
            entity_id=entity_res.entity_id,
            predicate=pred_res.canonical_predicate,
            predicate_mention=fact.predicate_mention or fact.predicate,
            value_text=fact.value_text,
            value_type=num_res.value_type,
            numeric_value=num_res.raw_numeric,
            normalized_numeric_value=num_res.normalized_numeric,
            unit=num_res.unit,
            normalized_unit=num_res.normalized_unit,
            currency=num_res.currency,
            time_text=date_res.time_text,
            time_start=date_res.time_start,
            time_end=date_res.time_end,
            time_granularity=date_res.time_granularity,
            scope=fact.scope,
            geography=fact.geography,
            qualifiers_json=fact.qualifiers_json,
            source_quote=fact.source_quote,
            source_page_start=fact.source_page_start,
            source_page_end=fact.source_page_end,
            source_block_ids_json=fact.source_block_ids_json,
            extraction_confidence=fact.extraction_confidence,
            validation_status=fact.validation_status,
            extraction_notes_json=fact.extraction_notes_json,
            created_at=fact.created_at,
        )

    def normalize_and_deduplicate_document(
        self, document_id: str
    ) -> list[FactSchema]:
        """Normalize all facts for a document and deduplicate identical claims."""
        conn = get_connection()
        try:
            # 1. Fetch document context
            doc = conn.execute(
                "SELECT metadata_json FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            doc_context = None
            if doc and doc["metadata_json"]:
                try:
                    doc_context = json.loads(doc["metadata_json"])
                except Exception:
                    pass

            # 2. Fetch facts for this document
            rows = conn.execute(
                "SELECT * FROM facts WHERE document_id = ?", (document_id,)
            ).fetchall()

            if not rows:
                return []

            facts = [
                FactSchema(
                    id=r["id"],
                    document_id=r["document_id"],
                    chunk_id=r["chunk_id"],
                    subject=r["subject"],
                    subject_mention=r["subject_mention"],
                    entity_id=r["entity_id"],
                    predicate=r["predicate"],
                    predicate_mention=r["predicate_mention"],
                    value_text=r["value_text"],
                    value_type=ValueType(r["value_type"]),
                    numeric_value=r["numeric_value"],
                    normalized_numeric_value=r["normalized_numeric_value"],
                    unit=r["unit"],
                    normalized_unit=r["normalized_unit"],
                    currency=r["currency"],
                    time_text=r["time_text"],
                    time_start=r["time_start"],
                    time_end=r["time_end"],
                    time_granularity=r["time_granularity"],
                    scope=r["scope"],
                    geography=r["geography"],
                    qualifiers_json=r["qualifiers_json"],
                    source_quote=r["source_quote"],
                    source_page_start=r["source_page_start"],
                    source_page_end=r["source_page_end"],
                    source_block_ids_json=r["source_block_ids_json"],
                    extraction_confidence=r["extraction_confidence"],
                    validation_status=ValidationStatus(r["validation_status"]),
                    extraction_notes_json=r["extraction_notes_json"],
                )
                for r in rows
            ]
        finally:
            conn.close()

        # 3. Apply normalization to each fact
        normalized_facts = [self.normalize_fact(f, doc_context) for f in facts]

        # 4. Same-document fact deduplication
        deduped_facts = deduplicate_facts(normalized_facts)

        # 5. Persist back to database
        self._persist_normalized_facts(document_id, deduped_facts)
        return deduped_facts

    def _persist_normalized_facts(
        self, document_id: str, facts: list[FactSchema]
    ) -> None:
        """Replace facts table rows with normalized and deduplicated facts."""
        conn = get_connection()
        try:
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
            conn.commit()
            logger.info("Persisted %d normalized facts for doc %s", len(facts), document_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
