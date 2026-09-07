"""V1 Reprocessing routes for documents and jobs."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, status

from app.db.database import get_connection
from app.models.schemas import CreateJobResponse
from app.workers.job_runner import get_job_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reprocess", tags=["reprocess"])


@router.post(
    "/{target_id}",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reprocess a document or retry an existing job",
)
async def reprocess(target_id: str) -> CreateJobResponse:
    """Trigger full reprocessing for either a document ID or an existing job ID.

    Returns HTTP 202 Accepted with the new job ID.
    """
    conn = get_connection()
    try:
        # 1. Check if target_id is a document
        doc = conn.execute("SELECT id FROM documents WHERE id = ?", (target_id,)).fetchone()
        if doc:
            runner = get_job_runner()
            jid = runner.start_job([target_id], mode="reprocess")
            return CreateJobResponse(job_id=jid, status="queued")

        # 2. Check if target_id is an existing job
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (target_id,)).fetchone()
        if job:
            doc_ids: list[str] = []
            if job["document_ids_json"]:
                try:
                    doc_ids = json.loads(job["document_ids_json"])
                except Exception:
                    pass
            runner = get_job_runner()
            jid = runner.start_job(doc_ids, mode="reprocess")
            return CreateJobResponse(job_id=jid, status="queued")

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target ID '{target_id}' matches neither an existing document nor job",
        )
    finally:
        conn.close()
