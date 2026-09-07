"""Hybrid Relationship Engine coordinating deterministic comparison and structured LLM evaluation."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Optional

from app.config import get_settings
from app.db.database import get_connection
from app.models.schemas import (
    CandidatePairSchema,
    CandidateStatus,
    EntitySchema,
    EntityType,
    FactSchema,
    PrimaryDimension,
    RelationshipSchema,
    RelationshipType,
    ValidationStatus,
    ValueType,
)
from app.services.reasoning.comparator import DeterministicComparator
from app.services.reasoning.models import LLMRelationshipClassification
from app.services.reasoning.prompts import build_relationship_messages
from app.services.reasoning.providers import (
    BaseRelationshipProvider,
    MockRelationshipProvider,
    OpenAIRelationshipProvider,
)

logger = logging.getLogger(__name__)

OPERATION_NAME = "relationship_reasoning"
PROMPT_VERSION = "v1"


class RelationshipEngine:
    """Orchestrator for deterministic fact comparison and LLM semantic relationship reasoning."""

    def __init__(
        self,
        provider: Optional[BaseRelationshipProvider] = None,
        comparator: Optional[DeterministicComparator] = None,
        db_path: Optional[str] = None,
        model: Optional[str] = None,
    ):
        settings = get_settings()
        self.db_path = db_path
        self.comparator = comparator or DeterministicComparator()
        self.model = model or settings.resolved_relationship_model or "gpt-4o"

        if provider is not None:
            self.provider = provider
        else:
            if settings.effective_api_key and not settings.effective_api_key.startswith("sk-test-"):
                self.provider = OpenAIRelationshipProvider()
            else:
                self.provider = MockRelationshipProvider()

    def _compute_input_hash(self, fact_a: FactSchema, fact_b: FactSchema) -> str:
        """Compute stable hash of the pair comparison inputs for caching."""
        payload = f"{fact_a.id}::{fact_a.value_text}::{fact_b.id}::{fact_b.value_text}::{PROMPT_VERSION}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _get_cached_classification(
        self, input_hash: str
    ) -> Optional[LLMRelationshipClassification]:
        """Check SQLite llm_cache for previous classification."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """SELECT response_json FROM llm_cache
                   WHERE operation = ? AND model = ? AND prompt_version = ? AND input_hash = ?""",
                (OPERATION_NAME, self.model, PROMPT_VERSION, input_hash),
            ).fetchone()
            if row:
                data = json.loads(row["response_json"])
                return LLMRelationshipClassification(**data)
            return None
        finally:
            conn.close()

    def _set_cached_classification(
        self, input_hash: str, classification: LLMRelationshipClassification
    ) -> None:
        """Store classification in SQLite llm_cache."""
        conn = get_connection(self.db_path)
        try:
            cache_id = str(uuid.uuid4())
            conn.execute(
                """INSERT OR REPLACE INTO llm_cache (id, operation, model, prompt_version, input_hash, response_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    cache_id,
                    OPERATION_NAME,
                    self.model,
                    PROMPT_VERSION,
                    input_hash,
                    classification.model_dump_json(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def evaluate_pair(
        self,
        fact_a: FactSchema,
        fact_b: FactSchema,
        entity_a: Optional[EntitySchema] = None,
        entity_b: Optional[EntitySchema] = None,
    ) -> RelationshipSchema:
        """Evaluate relationship between two facts using hybrid deterministic + LLM approach."""
        # ── Step 0: Reject facts that failed verification ────────────
        if (
            fact_a.validation_status in (ValidationStatus.REJECTED, "rejected")
            or fact_b.validation_status in (ValidationStatus.REJECTED, "rejected")
        ):
            rel_id = str(uuid.uuid4())
            rej_id = (
                fact_a.id
                if fact_a.validation_status in (ValidationStatus.REJECTED, "rejected")
                else fact_b.id
            )
            return RelationshipSchema(
                id=rel_id,
                fact_a_id=fact_a.id,
                fact_b_id=fact_b.id,
                relationship_type=RelationshipType.UNCERTAIN,
                confidence=0.0,
                primary_dimension=PrimaryDimension.VALUE,
                explanation=f"Cannot establish relationship because fact {rej_id} failed source evidence verification (rejected).",
                context_comparison_json=json.dumps({"rejected_fact_id": rej_id}),
            )

        # ── Step 1: Run Deterministic 9-Dimension Comparison ─────────
        is_conclusive, classification, context = self.comparator.compare(
            fact_a, fact_b, entity_a, entity_b
        )

        # ── Step 2: Fallback to LLM Only for Unresolved Judgment ─────
        if not is_conclusive or classification is None:
            input_hash = self._compute_input_hash(fact_a, fact_b)
            cached = self._get_cached_classification(input_hash)

            if cached:
                logger.info("LLM cache hit for relationship pair %s <-> %s", fact_a.id, fact_b.id)
                classification = cached
            else:
                messages = build_relationship_messages(
                    fact_a, fact_b, entity_a, entity_b, context
                )
                classification = self.provider.classify(messages, model=self.model)
                self._set_cached_classification(input_hash, classification)

        # ── Step 3: Build & Persist Relationship ─────────────────────
        rel_id = str(uuid.uuid4())
        relationship = RelationshipSchema(
            id=rel_id,
            fact_a_id=fact_a.id,
            fact_b_id=fact_b.id,
            relationship_type=classification.relationship_type,
            confidence=classification.confidence,
            primary_dimension=classification.primary_dimension,
            context_comparison_json=json.dumps(classification.context_comparison or context),
            explanation=classification.explanation,
            evidence_fact_a=fact_a.source_quote,
            evidence_fact_b=fact_b.source_quote,
            reasoning_version=PROMPT_VERSION,
        )

        conn = get_connection(self.db_path)
        try:
            # Check if referenced facts exist in database before inserting
            row_a = conn.execute("SELECT id FROM facts WHERE id = ?", (relationship.fact_a_id,)).fetchone()
            row_b = conn.execute("SELECT id FROM facts WHERE id = ?", (relationship.fact_b_id,)).fetchone()

            if row_a and row_b:
                conn.execute(
                    """INSERT OR REPLACE INTO relationships (
                        id, fact_a_id, fact_b_id, relationship_type, confidence,
                        primary_dimension, context_comparison_json, explanation,
                        evidence_fact_a, evidence_fact_b, reasoning_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        relationship.id,
                        relationship.fact_a_id,
                        relationship.fact_b_id,
                        relationship.relationship_type.value,
                        relationship.confidence,
                        relationship.primary_dimension.value if relationship.primary_dimension else None,
                        relationship.context_comparison_json,
                        relationship.explanation,
                        relationship.evidence_fact_a,
                        relationship.evidence_fact_b,
                        relationship.reasoning_version,
                    ),
                )

                # 2. Update candidate pair status to 'evaluated'
                conn.execute(
                    """UPDATE candidate_pairs SET status = ?
                       WHERE (fact_a_id = ? AND fact_b_id = ?)
                          OR (fact_a_id = ? AND fact_b_id = ?)""",
                    (
                        CandidateStatus.EVALUATED.value,
                        fact_a.id,
                        fact_b.id,
                        fact_b.id,
                        fact_a.id,
                    ),
                )
                conn.commit()
            else:
                logger.debug("Referenced facts %s and %s not in facts table; skipped relationship table insertion", fact_a.id, fact_b.id)
        finally:
            conn.close()

        return relationship

    def evaluate_candidates(
        self,
        document_id: Optional[str] = None,
        force: bool = False,
    ) -> list[RelationshipSchema]:
        """Evaluate pending candidate pairs from the database."""
        conn = get_connection(self.db_path)
        try:
            # Load candidate pairs
            query = "SELECT * FROM candidate_pairs"
            params: list = []
            if not force:
                query += " WHERE status = 'pending'"

            cp_rows = conn.execute(query, params).fetchall()
            if not cp_rows:
                return []

            # Load facts (strictly excluding rejected facts)
            fact_rows = conn.execute(
                "SELECT * FROM facts WHERE validation_status != 'rejected'"
            ).fetchall()
            facts_by_id = {
                r["id"]: FactSchema(
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
                for r in fact_rows
            }

            # Load entities
            entity_rows = conn.execute("SELECT * FROM entities").fetchall()
            entities_by_id = {
                r["id"]: EntitySchema(
                    id=r["id"],
                    canonical_name=r["canonical_name"],
                    entity_type=EntityType(r["entity_type"]),
                    confidence=r["confidence"],
                    metadata_json=r["metadata_json"],
                )
                for r in entity_rows
            }
        finally:
            conn.close()

        relationships: list[RelationshipSchema] = []
        for cp in cp_rows:
            f_a = facts_by_id.get(cp["fact_a_id"])
            f_b = facts_by_id.get(cp["fact_b_id"])
            if not f_a or not f_b:
                continue

            # If document_id is supplied, ensure at least one fact belongs to it
            if document_id and f_a.document_id != document_id and f_b.document_id != document_id:
                continue

            e_a = entities_by_id.get(f_a.entity_id or "")
            e_b = entities_by_id.get(f_b.entity_id or "")

            rel = self.evaluate_pair(f_a, f_b, e_a, e_b)
            relationships.append(rel)

        return relationships
