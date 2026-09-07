"""Candidate generation pipeline for semantic and structured fact pair retrieval."""

from __future__ import annotations

import difflib
import json
import logging
import re
import uuid
from typing import Optional

from app.config import get_settings
from app.db.database import get_connection
from app.models.schemas import (
    CandidatePairSchema,
    CandidateStatus,
    EntitySchema,
    EntityType,
    FactSchema,
    ValidationStatus,
    ValueType,
)
from app.services.matching.embeddings import (
    EmbeddingService,
    cosine_similarity,
)
from app.services.normalization.predicates import CANONICAL_PREDICATE_MAP

logger = logging.getLogger(__name__)


# ── Semantic Predicate Families ───────────────────────────────────────

# Related business metrics that are comparable but not identical
PREDICATE_FAMILIES: dict[str, set[str]] = {
    "top_line": {"revenue", "sales"},
    "profitability": {"operating_income", "net_income", "operating_margin", "gross_margin", "net_margin"},
    "headcount": {"employee_count"},
    "leadership": {"chief_executive_officer", "chief_financial_officer", "founder", "chairman"},
    "market": {"market_cap", "valuation", "share_price"},
}


# ── Compatibility & Similarity Helpers ────────────────────────────────


def check_entity_compatibility_and_similarity(
    fact_a: FactSchema,
    fact_b: FactSchema,
    entity_a: Optional[EntitySchema] = None,
    entity_b: Optional[EntitySchema] = None,
) -> tuple[bool, float, list[str]]:
    """Check entity type compatibility and compute entity similarity.

    Returns:
        (is_compatible, similarity_score, reasons)
    """
    reasons: list[str] = []

    # 1. Type compatibility check
    if entity_a and entity_b:
        type_a = entity_a.entity_type
        type_b = entity_b.entity_type
        if (
            type_a != type_b
            and type_a != EntityType.OTHER
            and type_b != EntityType.OTHER
        ):
            return False, 0.0, [f"incompatible entity types: {type_a.value} vs {type_b.value}"]

    # 2. Canonical entity match
    if fact_a.entity_id and fact_b.entity_id and fact_a.entity_id == fact_b.entity_id:
        reasons.append("same canonical entity")
        return True, 1.0, reasons

    # 3. Canonical name match
    name_a = (entity_a.canonical_name if entity_a else fact_a.subject).strip().lower()
    name_b = (entity_b.canonical_name if entity_b else fact_b.subject).strip().lower()

    if name_a and name_a == name_b:
        reasons.append("same canonical entity")
        return True, 1.0, reasons

    # 4. Token overlap and fuzzy string similarity
    ratio = difflib.SequenceMatcher(None, name_a, name_b).ratio()
    tokens_a = set(name_a.split())
    tokens_b = set(name_b.split())
    jaccard = (
        len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        if (tokens_a | tokens_b)
        else 0.0
    )

    similarity = max(ratio, jaccard)
    if similarity >= 0.80:
        reasons.append(f"entity semantic similarity {similarity:.2f}")
        return True, round(similarity, 2), reasons
    elif similarity >= 0.50:
        return True, round(similarity, 2), reasons

    # Low entity similarity
    return True, round(similarity, 2), reasons


def check_predicate_similarity(
    fact_a: FactSchema, fact_b: FactSchema
) -> tuple[float, list[str]]:
    """Compute predicate similarity and selection reasons."""
    reasons: list[str] = []
    pred_a = (fact_a.predicate or "").strip().lower()
    pred_b = (fact_b.predicate or "").strip().lower()

    # Exact canonical predicate match
    if pred_a == pred_b:
        reasons.append(f"exact predicate match: {pred_a}")
        return 1.0, reasons

    # Check semantic predicate families (e.g. revenue and sales)
    for family_name, members in PREDICATE_FAMILIES.items():
        if pred_a in members and pred_b in members:
            # High semantic similarity between related family members
            reasons.append("predicate semantic similarity 0.91")
            return 0.91, reasons

    # String similarity
    ratio = difflib.SequenceMatcher(None, pred_a, pred_b).ratio()
    if ratio >= 0.70:
        reasons.append(f"predicate semantic similarity {ratio:.2f}")
        return round(ratio, 2), reasons

    return round(ratio, 2), reasons


def check_unit_compatibility(
    fact_a: FactSchema, fact_b: FactSchema
) -> tuple[Optional[bool], list[str]]:
    """Check unit and currency compatibility between two facts."""
    reasons: list[str] = []

    # 1. Currency compatibility
    curr_a = (fact_a.currency or "").strip().upper()
    curr_b = (fact_b.currency or "").strip().upper()

    if curr_a and curr_b:
        if curr_a == curr_b:
            reasons.append(f"same currency {curr_a}")
        else:
            return False, [f"incompatible currencies: {curr_a} vs {curr_b}"]

    # 2. Unit & Value Type compatibility
    is_pct_a = (
        fact_a.value_type == ValueType.PERCENTAGE
        or (fact_a.unit or "").strip() == "%"
        or (fact_a.normalized_unit or "").strip() == "%"
    )
    is_pct_b = (
        fact_b.value_type == ValueType.PERCENTAGE
        or (fact_b.unit or "").strip() == "%"
        or (fact_b.normalized_unit or "").strip() == "%"
    )

    is_mon_a = fact_a.value_type == ValueType.CURRENCY or bool(curr_a)
    is_mon_b = fact_b.value_type == ValueType.CURRENCY or bool(curr_b)

    # Reject percentage vs monetary
    if (is_pct_a and is_mon_b) or (is_mon_a and is_pct_b):
        return False, ["incompatible units: percentage vs monetary"]

    # Reject percentage vs count/ratio if one is percentage and other is not
    unit_a = (fact_a.normalized_unit or fact_a.unit or "").strip().lower()
    unit_b = (fact_b.normalized_unit or fact_b.unit or "").strip().lower()

    if unit_a and unit_b:
        if unit_a == unit_b:
            reasons.append(f"same unit {unit_a}")
            return True, reasons
        # Different non-empty units
        if is_pct_a != is_pct_b:
            return False, [f"incompatible units: {unit_a} vs {unit_b}"]

    return True, reasons


def check_temporal_compatibility(
    fact_a: FactSchema, fact_b: FactSchema
) -> tuple[Optional[bool], list[str]]:
    """Check temporal compatibility (e.g. same fiscal year, overlapping periods)."""
    reasons: list[str] = []

    t_text_a = (fact_a.time_text or "").strip().lower()
    t_text_b = (fact_b.time_text or "").strip().lower()

    def _extract_year(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        m = re.search(r"(?:(?:fy|fiscal\s*(?:year)?)\s*)?(20\d{2}|19\d{2})", text.lower())
        return m.group(1) if m else None

    # Extract year from time_text or time_start
    year_a = _extract_year(fact_a.time_text) or _extract_year(fact_a.time_start)
    year_b = _extract_year(fact_b.time_text) or _extract_year(fact_b.time_start)

    if year_a and year_b:
        if year_a == year_b:
            reasons.append("same fiscal year")
            return True, reasons
        else:
            return False, [f"different fiscal years: {year_a} vs {year_b}"]

    # Identical ISO dates or spans
    if fact_a.time_start and fact_b.time_start:
        if (
            fact_a.time_start == fact_b.time_start
            and fact_a.time_end == fact_b.time_end
        ):
            reasons.append("identical time period")
            return True, reasons

    # If times are unspecified, it's not incompatible, but no strong temporal link
    if not t_text_a and not fact_a.time_start and not t_text_b and not fact_b.time_start:
        return None, []

    return True, reasons


def check_scope_compatibility(
    fact_a: FactSchema, fact_b: FactSchema
) -> tuple[Optional[bool], list[str]]:
    """Check scope and geography compatibility."""
    reasons: list[str] = []
    scope_a = (fact_a.scope or "").strip().lower()
    scope_b = (fact_b.scope or "").strip().lower()

    if scope_a and scope_b:
        if scope_a == scope_b:
            reasons.append(f"same scope {scope_a}")
            return True, reasons

    geo_a = (fact_a.geography or "").strip().lower()
    geo_b = (fact_b.geography or "").strip().lower()

    if geo_a and geo_b:
        if geo_a == geo_b:
            reasons.append(f"same geography {geo_a}")
            return True, reasons

    return True, reasons


# ── Candidate Generator ───────────────────────────────────────────────


class CandidateGenerator:
    """Pipeline for conservative semantic and structured candidate fact pair generation."""

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        db_path: Optional[str] = None,
        min_score: Optional[float] = None,
        top_k: Optional[int] = None,
    ):
        settings = get_settings()
        self.embedding_service = embedding_service or EmbeddingService(db_path=db_path)
        self.db_path = db_path
        self.min_score = min_score if min_score is not None else settings.candidate_min_score
        self.top_k = top_k if top_k is not None else settings.candidate_top_k

    def evaluate_pair(
        self,
        fact_a: FactSchema,
        fact_b: FactSchema,
        entity_a: Optional[EntitySchema] = None,
        entity_b: Optional[EntitySchema] = None,
        vector_a: Optional[list[float]] = None,
        vector_b: Optional[list[float]] = None,
    ) -> Optional[CandidatePairSchema]:
        """Evaluate a pair of facts and return CandidatePairSchema if plausible.

        Conservative rules:
        - Exclude same fact.
        - Reject clearly incompatible entity types.
        - Reject incompatible units (e.g. % vs USD).
        - Compute composite candidate score.
        - Retain only if score >= min_score.
        - Do NOT call relationship LLM.
        """
        # 1. Exclude same fact or rejected facts that failed verification
        if fact_a.id == fact_b.id:
            return None
        if (
            fact_a.validation_status == ValidationStatus.REJECTED
            or fact_b.validation_status == ValidationStatus.REJECTED
        ):
            return None

        # 2. Reject clearly incompatible entity types & check entity similarity
        compat_entity, entity_sim, entity_reasons = (
            check_entity_compatibility_and_similarity(
                fact_a, fact_b, entity_a, entity_b
            )
        )
        if not compat_entity:
            return None

        # 3. Check unit compatibility
        compat_unit, unit_reasons = check_unit_compatibility(fact_a, fact_b)
        if compat_unit is False:
            return None

        # 4. Check temporal compatibility
        compat_period, temp_reasons = check_temporal_compatibility(fact_a, fact_b)

        # 5. Check scope compatibility
        compat_scope, scope_reasons = check_scope_compatibility(fact_a, fact_b)

        # 6. Predicate similarity
        pred_sim, pred_reasons = check_predicate_similarity(fact_a, fact_b)

        # 7. Semantic / Embedding similarity
        sem_sim = 0.0
        embedding_reasons: list[str] = []
        if vector_a and vector_b:
            raw_sim = cosine_similarity(vector_a, vector_b)
            # Embedding cosine similarity can be negative, normalize to [0, 1] for retrieval
            sem_sim = max(0.0, raw_sim)
            if sem_sim >= 0.70:
                embedding_reasons.append(f"embedding similarity {sem_sim:.2f}")

        # 8. Compile explainable selection reasons
        all_reasons = (
            entity_reasons
            + pred_reasons
            + temp_reasons
            + scope_reasons
            + unit_reasons
            + embedding_reasons
        )

        # 9. Conservative Scoring
        # Cross-document bonus
        same_document = fact_a.document_id == fact_b.document_id
        cross_doc_bonus = 0.05 if not same_document else 0.0

        # Temporal bonus/penalty
        temp_score = 0.10 if compat_period is True else (0.05 if compat_period is None else 0.0)

        # Base formula: entity (0.30) + predicate (0.30) + embedding (0.25) + temporal (0.10) + cross_doc (0.05)
        composite = (
            (entity_sim * 0.30)
            + (pred_sim * 0.30)
            + (sem_sim * 0.25)
            + temp_score
            + cross_doc_bonus
        )

        candidate_score = round(min(1.0, max(0.0, composite)), 2)

        # Check threshold
        if candidate_score < self.min_score:
            return None

        pair_id = str(uuid.uuid4())
        return CandidatePairSchema(
            id=pair_id,
            fact_a_id=fact_a.id,
            fact_b_id=fact_b.id,
            same_document=same_document,
            entity_similarity=entity_sim,
            predicate_similarity=pred_sim,
            semantic_similarity=round(sem_sim, 2),
            unit_compatible=compat_unit,
            period_compatible=compat_period,
            scope_compatible=compat_scope,
            candidate_score=candidate_score,
            reason_json=json.dumps(all_reasons),
            status=CandidateStatus.PENDING,
        )

    def generate_candidates(
        self,
        document_id: Optional[str] = None,
        cross_document_only: bool = False,
        min_score: Optional[float] = None,
        top_k: Optional[int] = None,
    ) -> list[CandidatePairSchema]:
        """Run candidate generation pipeline across facts in the database."""
        effective_min_score = min_score if min_score is not None else self.min_score
        effective_top_k = top_k if top_k is not None else self.top_k

        conn = get_connection(self.db_path)
        try:
            # 1. Load entities
            entity_rows = conn.execute("SELECT * FROM entities").fetchall()
            entities_by_id: dict[str, EntitySchema] = {
                r["id"]: EntitySchema(
                    id=r["id"],
                    canonical_name=r["canonical_name"],
                    entity_type=EntityType(r["entity_type"]),
                    confidence=r["confidence"],
                    metadata_json=r["metadata_json"],
                )
                for r in entity_rows
            }
            entity_name_lookup = {
                e.id: e.canonical_name for e in entities_by_id.values()
            }

            # 2. Load facts (strictly excluding rejected facts)
            query = "SELECT * FROM facts WHERE validation_status != 'rejected'"
            params: list = []
            if document_id and not cross_document_only:
                # If specific document requested and not cross-doc only, load facts for this doc
                query += " AND document_id = ?"
                params.append(document_id)

            fact_rows = conn.execute(query, params).fetchall()
            if not fact_rows:
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
                for r in fact_rows
            ]

            # 3. Ensure embeddings exist for these facts
            self.embedding_service.embed_facts(facts, entity_name_lookup)
            vectors_by_fact_id = self.embedding_service.get_fact_embeddings_batch(
                [f.id for f in facts]
            )

            # 4. Pairwise comparison with canonical ordering to avoid reciprocal pairs
            # fact_a_id < fact_b_id
            candidates_per_fact: dict[str, list[CandidatePairSchema]] = {}

            for i in range(len(facts)):
                f_a = facts[i]
                v_a = vectors_by_fact_id.get(f_a.id)
                e_a = entities_by_id.get(f_a.entity_id or "")

                for j in range(i + 1, len(facts)):
                    f_b = facts[j]

                    if cross_document_only and f_a.document_id == f_b.document_id:
                        continue

                    # If specific document_id requested for candidate generation,
                    # at least one of the facts should belong to document_id
                    if document_id and f_a.document_id != document_id and f_b.document_id != document_id:
                        continue

                    v_b = vectors_by_fact_id.get(f_b.id)
                    e_b = entities_by_id.get(f_b.entity_id or "")

                    # Enforce consistent fact_a_id < fact_b_id
                    first, second = (f_a, f_b) if f_a.id < f_b.id else (f_b, f_a)
                    first_v, second_v = (v_a, v_b) if f_a.id < f_b.id else (v_b, v_a)
                    first_e, second_e = (e_a, e_b) if f_a.id < f_b.id else (e_b, e_a)

                    pair = self.evaluate_pair(
                        first, second, first_e, second_e, first_v, second_v
                    )

                    if pair and pair.candidate_score >= effective_min_score:
                        candidates_per_fact.setdefault(first.id, []).append(pair)
                        candidates_per_fact.setdefault(second.id, []).append(pair)

            # 5. Retain top_k per fact and deduplicate pairs
            selected_pairs: dict[str, CandidatePairSchema] = {}
            for f_id, pairs in candidates_per_fact.items():
                # Sort by score descending, then prefer cross-document
                pairs.sort(
                    key=lambda p: (p.candidate_score, not p.same_document),
                    reverse=True,
                )
                for p in pairs[:effective_top_k]:
                    pair_key = f"{p.fact_a_id}::{p.fact_b_id}"
                    if pair_key not in selected_pairs:
                        selected_pairs[pair_key] = p

            results = list(selected_pairs.values())
            # Final global sort
            results.sort(
                key=lambda p: (p.candidate_score, not p.same_document),
                reverse=True,
            )

            # 6. Persist to candidate_pairs table
            self._persist_candidates(conn, results)
            return results
        finally:
            conn.close()

    def _persist_candidates(self, conn, candidates: list[CandidatePairSchema]) -> None:
        """Persist generated candidate pairs into SQLite table."""
        for p in candidates:
            conn.execute(
                """INSERT OR REPLACE INTO candidate_pairs (
                    id, fact_a_id, fact_b_id, same_document,
                    entity_similarity, predicate_similarity, semantic_similarity,
                    unit_compatible, period_compatible, scope_compatible,
                    candidate_score, reason_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p.id,
                    p.fact_a_id,
                    p.fact_b_id,
                    1 if p.same_document else 0,
                    p.entity_similarity,
                    p.predicate_similarity,
                    p.semantic_similarity,
                    None if p.unit_compatible is None else (1 if p.unit_compatible else 0),
                    None if p.period_compatible is None else (1 if p.period_compatible else 0),
                    None if p.scope_compatible is None else (1 if p.scope_compatible else 0),
                    p.candidate_score,
                    p.reason_json,
                    p.status.value if hasattr(p.status, "value") else str(p.status),
                ),
            )
        conn.commit()
