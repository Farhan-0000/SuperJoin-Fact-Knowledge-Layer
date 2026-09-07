"""V1 Asynchronous job management routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.db.database import get_connection
from app.models.schemas import (
    CreateJobRequest,
    CreateJobResponse,
    JobStatusResponse,
)
from app.workers.job_runner import get_job_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start asynchronous processing job",
)
async def create_job(request: CreateJobRequest) -> CreateJobResponse:
    """Enqueue an asynchronous pipeline execution job across the specified document IDs.

    Returns HTTP 202 Accepted with the newly created job ID.
    """
    if not request.document_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one document ID must be specified to start a job",
        )

    # Validate that the documents exist
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in request.document_ids)
        rows = conn.execute(
            f"SELECT id FROM documents WHERE id IN ({placeholders})",
            request.document_ids,
        ).fetchall()
        found_ids = {r["id"] for r in rows}
        missing = [d for d in request.document_ids if d not in found_ids]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"The following document IDs were not found: {missing}",
            )
    finally:
        conn.close()

    runner = get_job_runner()
    job_id = runner.start_job(
        document_ids=request.document_ids,
        mode=request.mode,
    )

    return CreateJobResponse(job_id=job_id, status="queued")


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job progress and status",
)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Retrieve execution state, stage, progress, and completed item count for a job."""
    runner = get_job_runner()
    job = runner.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    return JobStatusResponse(
        id=job.id,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        stage=job.current_stage,
        progress=round(job.progress, 2),
        completed_items=job.completed_items,
        total_items=job.total_items,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
