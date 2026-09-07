"""Health and system routes."""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter

from app.db.database import get_connection
from app.models.schemas import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return application health status including database connectivity."""
    db_status = "connected"
    doc_count = 0

    try:
        conn = get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM documents").fetchone()
            doc_count = row["cnt"] if row else 0
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        db_status = f"error: {exc}"

    return HealthResponse(
        status="ok",
        version="0.1.0",
        database=db_status,
        documents_count=doc_count,
    )
