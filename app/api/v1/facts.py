"""V1 Fact query and detail routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.db.database import get_connection
from app.models.schemas import FactSchema, ValidationStatus, ValueType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/facts", tags=["facts"])


@router.get("", response_model=list[FactSchema], summary="Query and filter facts")
def list_facts(
    document_id: Optional[str] = Query(None, description="Filter facts by document ID"),
    entity: Optional[str] = Query(None, description="Filter facts by subject/entity keyword"),
    predicate: Optional[str] = Query(None, description="Filter facts by predicate keyword"),
    validation_status: Optional[str] = Query(None, description="Filter by validation status (validated, warning, rejected)"),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum extraction confidence"),
    limit: int = Query(50, ge=1, le=500, description="Max facts to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> list[FactSchema]:
    """Retrieve extracted facts with filtering and pagination."""
    conn = get_connection()
    try:
        query = """
            SELECT f.* FROM facts f
            LEFT JOIN entities e ON f.entity_id = e.id
            WHERE 1=1
        """
        params: list[object] = []

        if document_id:
            query += " AND f.document_id = ?"
            params.append(document_id)
        if entity:
            query += " AND (f.subject LIKE ? OR e.canonical_name LIKE ?)"
            params.extend([f"%{entity}%", f"%{entity}%"])
        if predicate:
            query += " AND f.predicate LIKE ?"
            params.append(f"%{predicate}%")
        if validation_status:
            query += " AND f.validation_status = ?"
            params.append(validation_status)
        if min_confidence is not None:
            query += " AND f.extraction_confidence >= ?"
            params.append(min_confidence)

        query += " ORDER BY f.rowid DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [
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
                created_at=r["created_at"],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/{fact_id}", response_model=FactSchema, summary="Get fact details by ID")
def get_fact(fact_id: str) -> FactSchema:
    """Retrieve a single fact by its unique ID with complete provenance."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Fact '{fact_id}' not found",
            )
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
            created_at=row["created_at"],
        )
    finally:
        conn.close()
