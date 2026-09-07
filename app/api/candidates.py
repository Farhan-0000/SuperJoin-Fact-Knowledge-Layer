"""Candidate pair query and generation routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.db.database import get_connection
from app.models.schemas import CandidatePairSchema, CandidateStatus
from app.services.matching.candidates import CandidateGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/candidates", tags=["candidates"])


class GenerateCandidatesRequest(BaseModel):
    """Payload for initiating candidate generation."""

    document_id: Optional[str] = Field(
        default=None, description="Optional document ID to generate candidates for"
    )
    cross_document_only: bool = Field(
        default=False, description="Whether to only evaluate cross-document pairs"
    )
    min_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Minimum candidate score to retain"
    )
    top_k: Optional[int] = Field(
        default=None, ge=1, le=100, description="Max candidates per fact"
    )


@router.post(
    "/generate",
    response_model=list[CandidatePairSchema],
    status_code=status.HTTP_201_CREATED,
    summary="Generate candidate fact pairs",
)
def generate_candidates(
    request: GenerateCandidatesRequest,
) -> list[CandidatePairSchema]:
    """Execute candidate generation pipeline across facts and persist results."""
    generator = CandidateGenerator(
        min_score=request.min_score,
        top_k=request.top_k,
    )
    return generator.generate_candidates(
        document_id=request.document_id,
        cross_document_only=request.cross_document_only,
        min_score=request.min_score,
        top_k=request.top_k,
    )


@router.get("", response_model=list[CandidatePairSchema], summary="List candidate pairs")
def list_candidates(
    document_id: Optional[str] = Query(None, description="Filter pairs by document ID"),
    fact_id: Optional[str] = Query(None, description="Filter pairs containing this fact ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (pending, evaluated, skipped)"),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum candidate score"),
    limit: int = Query(50, ge=1, le=500, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[CandidatePairSchema]:
    """Retrieve candidate pairs with filtering and pagination."""
    conn = get_connection()
    try:
        query = "SELECT * FROM candidate_pairs WHERE 1=1"
        params: list[object] = []

        if fact_id:
            query += " AND (fact_a_id = ? OR fact_b_id = ?)"
            params.extend([fact_id, fact_id])
        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)
        if min_score is not None:
            query += " AND candidate_score >= ?"
            params.append(min_score)

        query += " ORDER BY candidate_score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [
            CandidatePairSchema(
                id=r["id"],
                fact_a_id=r["fact_a_id"],
                fact_b_id=r["fact_b_id"],
                same_document=bool(r["same_document"]),
                entity_similarity=r["entity_similarity"],
                predicate_similarity=r["predicate_similarity"],
                semantic_similarity=r["semantic_similarity"],
                unit_compatible=bool(r["unit_compatible"]) if r["unit_compatible"] is not None else None,
                period_compatible=bool(r["period_compatible"]) if r["period_compatible"] is not None else None,
                scope_compatible=bool(r["scope_compatible"]) if r["scope_compatible"] is not None else None,
                candidate_score=r["candidate_score"],
                reason_json=r["reason_json"],
                status=CandidateStatus(r["status"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get(
    "/{pair_id}",
    response_model=CandidatePairSchema,
    summary="Get candidate pair by ID",
)
def get_candidate(pair_id: str) -> CandidatePairSchema:
    """Retrieve a single candidate pair by its unique ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM candidate_pairs WHERE id = ?", (pair_id,)
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Candidate pair '{pair_id}' not found",
            )
        return CandidatePairSchema(
            id=row["id"],
            fact_a_id=row["fact_a_id"],
            fact_b_id=row["fact_b_id"],
            same_document=bool(row["same_document"]),
            entity_similarity=row["entity_similarity"],
            predicate_similarity=row["predicate_similarity"],
            semantic_similarity=row["semantic_similarity"],
            unit_compatible=bool(row["unit_compatible"]) if row["unit_compatible"] is not None else None,
            period_compatible=bool(row["period_compatible"]) if row["period_compatible"] is not None else None,
            scope_compatible=bool(row["scope_compatible"]) if row["scope_compatible"] is not None else None,
            candidate_score=row["candidate_score"],
            reason_json=row["reason_json"],
            status=CandidateStatus(row["status"]),
            created_at=row["created_at"],
        )
    finally:
        conn.close()
