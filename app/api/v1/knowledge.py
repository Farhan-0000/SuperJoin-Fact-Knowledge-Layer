"""V1 Knowledge base summary and analytics routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.db.database import get_connection
from app.models.schemas import KnowledgeSummarySchema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/summary", response_model=KnowledgeSummarySchema, summary="Get knowledge layer statistics")
def get_knowledge_summary() -> KnowledgeSummarySchema:
    """Return aggregated counts of documents, facts, validations, and relationships."""
    conn = get_connection()
    try:
        # Documents count
        doc_count = conn.execute("SELECT COUNT(*) as c FROM documents").fetchone()["c"]

        # Facts counts
        facts_row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN validation_status = 'validated' THEN 1 ELSE 0 END) as validated,
                SUM(CASE WHEN validation_status = 'warning' THEN 1 ELSE 0 END) as warning,
                SUM(CASE WHEN validation_status = 'rejected' THEN 1 ELSE 0 END) as rejected
               FROM facts"""
        ).fetchone()

        # Relationships counts
        rel_row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN relationship_type = 'corroborates' THEN 1 ELSE 0 END) as corroborates,
                SUM(CASE WHEN relationship_type = 'contradicts' THEN 1 ELSE 0 END) as contradicts,
                SUM(CASE WHEN relationship_type = 'reconciles' THEN 1 ELSE 0 END) as reconciles,
                SUM(CASE WHEN relationship_type = 'uncertain' THEN 1 ELSE 0 END) as uncertain,
                SUM(CASE WHEN relationship_type = 'unrelated' THEN 1 ELSE 0 END) as unrelated
               FROM relationships"""
        ).fetchone()

        # Entities count
        ent_count = conn.execute("SELECT COUNT(*) as c FROM entities").fetchone()["c"]

        return KnowledgeSummarySchema(
            documents=doc_count,
            facts=facts_row["total"] or 0,
            validated_facts=facts_row["validated"] or 0,
            warnings=facts_row["warning"] or 0,
            rejected=facts_row["rejected"] or 0,
            relationships=rel_row["total"] or 0,
            corroborations=rel_row["corroborates"] or 0,
            contradictions=rel_row["contradicts"] or 0,
            reconciliations=rel_row["reconciles"] or 0,
            uncertain=rel_row["uncertain"] or 0,
            unrelated=rel_row["unrelated"] or 0,
            entities=ent_count,
        )
    finally:
        conn.close()
