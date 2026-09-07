"""Relationship query and evaluation routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.db.database import get_connection
from app.models.schemas import (
    PrimaryDimension,
    RelationshipSchema,
    RelationshipType,
)
from app.services.reasoning.engine import RelationshipEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/relationships", tags=["relationships"])


class EvaluateRelationshipsRequest(BaseModel):
    """Payload for evaluating candidate relationships."""

    document_id: Optional[str] = Field(
        default=None, description="Optional document ID to evaluate candidates for"
    )
    force: bool = Field(
        default=False, description="Re-evaluate candidate pairs even if already evaluated"
    )


@router.post(
    "/evaluate",
    response_model=list[RelationshipSchema],
    status_code=status.HTTP_201_CREATED,
    summary="Evaluate pending candidate pairs",
)
def evaluate_relationships(
    request: EvaluateRelationshipsRequest,
) -> list[RelationshipSchema]:
    """Run hybrid relationship reasoning pipeline over pending candidate pairs."""
    engine = RelationshipEngine()
    return engine.evaluate_candidates(
        document_id=request.document_id,
        force=request.force,
    )


@router.get("", response_model=list[RelationshipSchema], summary="List relationships")
def list_relationships(
    relationship_type: Optional[str] = Query(None, description="Filter by type (corroborates, contradicts, reconciles, uncertain, unrelated)"),
    primary_dimension: Optional[str] = Query(None, description="Filter by dimension (value, time, scope, unit, entity, definition, geography, other)"),
    fact_id: Optional[str] = Query(None, description="Filter relationships involving this fact ID"),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum relationship confidence"),
    limit: int = Query(50, ge=1, le=500, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[RelationshipSchema]:
    """Retrieve classified relationships with filtering and pagination."""
    conn = get_connection()
    try:
        query = "SELECT * FROM relationships WHERE 1=1"
        params: list[object] = []

        if relationship_type:
            query += " AND relationship_type = ?"
            params.append(relationship_type)
        if primary_dimension:
            query += " AND primary_dimension = ?"
            params.append(primary_dimension)
        if fact_id:
            query += " AND (fact_a_id = ? OR fact_b_id = ?)"
            params.extend([fact_id, fact_id])
        if min_confidence is not None:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        query += " ORDER BY confidence DESC, created_at DESC LIMIT ? OFFSET ?"
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


@router.get(
    "/{relationship_id}",
    response_model=RelationshipSchema,
    summary="Get relationship by ID",
)
def get_relationship(relationship_id: str) -> RelationshipSchema:
    """Retrieve a single relationship by its unique ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM relationships WHERE id = ?", (relationship_id,)
        ).fetchone()
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
