"""V1 Relationship query and detail routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.db.database import get_connection
from app.models.schemas import (
    PrimaryDimension,
    RelationshipSchema,
    RelationshipType,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/relationships", tags=["relationships"])


@router.get("", response_model=list[RelationshipSchema], summary="Query and filter relationships")
def list_relationships(
    rel_type: Optional[str] = Query(None, alias="type", description="Filter by relationship type (corroborates, contradicts, reconciles, uncertain, unrelated)"),
    document_id: Optional[str] = Query(None, description="Filter relationships involving facts from this document ID"),
    confidence: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum confidence threshold"),
    primary_dimension: Optional[str] = Query(None, description="Filter by primary dimension (value, time, scope, unit, entity, definition, geography, other)"),
    fact_id: Optional[str] = Query(None, description="Filter relationships involving this specific fact ID"),
    limit: int = Query(50, ge=1, le=500, description="Max relationships to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> list[RelationshipSchema]:
    """Retrieve classified relationships with multi-dimensional filtering."""
    conn = get_connection()
    try:
        query = """
            SELECT r.* FROM relationships r
            JOIN facts fa ON r.fact_a_id = fa.id
            JOIN facts fb ON r.fact_b_id = fb.id
            WHERE 1=1
        """
        params: list[object] = []

        if rel_type:
            query += " AND r.relationship_type = ?"
            params.append(rel_type.lower())
        if primary_dimension:
            query += " AND r.primary_dimension = ?"
            params.append(primary_dimension.lower())
        if confidence is not None:
            query += " AND r.confidence >= ?"
            params.append(confidence)
        if fact_id:
            query += " AND (r.fact_a_id = ? OR r.fact_b_id = ?)"
            params.extend([fact_id, fact_id])
        if document_id:
            query += " AND (fa.document_id = ? OR fb.document_id = ?)"
            params.extend([document_id, document_id])

        query += " ORDER BY r.confidence DESC, r.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [
            RelationshipSchema(
                id=r["id"],
                fact_a_id=r["fact_a_id"],
                fact_b_id=r["fact_b_id"],
                relationship_type=RelationshipType(r["relationship_type"]),
                confidence=r["confidence"],
                primary_dimension=PrimaryDimension(r["primary_dimension"]) if r["primary_dimension"] else None,
                context_comparison_json=r["context_comparison_json"],
                explanation=r["explanation"],
                evidence_fact_a=r["evidence_fact_a"],
                evidence_fact_b=r["evidence_fact_b"],
                reasoning_version=r["reasoning_version"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/{relationship_id}", response_model=RelationshipSchema, summary="Get relationship details")
def get_relationship(relationship_id: str) -> RelationshipSchema:
    """Retrieve detailed relationship object with source evidence quotes and context comparison."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM relationships WHERE id = ?", (relationship_id,)).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Relationship '{relationship_id}' not found",
            )
        return RelationshipSchema(
            id=row["id"],
            fact_a_id=row["fact_a_id"],
            fact_b_id=row["fact_b_id"],
            relationship_type=RelationshipType(row["relationship_type"]),
            confidence=row["confidence"],
            primary_dimension=PrimaryDimension(row["primary_dimension"]) if row["primary_dimension"] else None,
            context_comparison_json=row["context_comparison_json"],
            explanation=row["explanation"],
            evidence_fact_a=row["evidence_fact_a"],
            evidence_fact_b=row["evidence_fact_b"],
            reasoning_version=row["reasoning_version"],
            created_at=row["created_at"],
        )
    finally:
        conn.close()
