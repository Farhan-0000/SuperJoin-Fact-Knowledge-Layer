"""Lightweight asynchronous local job runner for single-machine pipeline execution."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid
from typing import Optional

from app.db.database import get_connection
from app.models.schemas import JobSchema, JobStatus, JobType
from app.services.ingestion.chunker import LayoutAwareChunker
from app.services.extraction.service import ExtractionService
from app.services.matching.candidates import CandidateGenerator
from app.services.normalization.pipeline import NormalizationPipeline
from app.services.reasoning.engine import RelationshipEngine

logger = logging.getLogger(__name__)


class LocalJobRunner:
    """In-process asynchronous job runner managing pipeline execution and state persistence in SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._running_tasks: set[asyncio.Task] = set()

    def _update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        progress: Optional[float] = None,
        completed_items: Optional[int] = None,
        total_items: Optional[int] = None,
        error_message: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """Update job fields in SQLite database."""
        conn = get_connection(self.db_path)
        try:
            updates: list[str] = []
            params: list = []

            if status is not None:
                updates.append("status = ?")
                params.append(status)
            if stage is not None:
                updates.append("current_stage = ?")
                params.append(stage)
            if progress is not None:
                updates.append("progress = ?")
                params.append(progress)
            if completed_items is not None:
                updates.append("completed_items = ?")
                params.append(completed_items)
            if total_items is not None:
                updates.append("total_items = ?")
                params.append(total_items)
            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)
            if started_at is not None:
                updates.append("started_at = ?")
                params.append(started_at)
            if completed_at is not None:
                updates.append("completed_at = ?")
                params.append(completed_at)

            if updates:
                params.append(job_id)
                sql = f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?"
                conn.execute(sql, params)
                conn.commit()
        finally:
            conn.close()

    def get_job(self, job_id: str) -> Optional[JobSchema]:
        """Fetch current status and progress of a job from SQLite."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return JobSchema(
                id=row["id"],
                job_type=JobType(row["job_type"]),
                document_ids_json=row["document_ids_json"],
                status=JobStatus(row["status"]),
                progress=row["progress"],
                current_stage=row["current_stage"],
                total_items=row["total_items"],
                completed_items=row["completed_items"],
                error_message=row["error_message"],
                created_at=row["created_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
            )
        finally:
            conn.close()

    async def run_pipeline(
        self,
        job_id: str,
        document_ids: list[str],
        mode: str = "full",
    ) -> None:
        """Asynchronously execute pipeline stages for the given document IDs."""
        logger.info("Starting pipeline execution for job %s (mode=%s, docs=%s)", job_id, mode, document_ids)
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._update_job(
            job_id,
            status=JobStatus.RUNNING.value,
            started_at=now_str,
            stage="chunking",
            progress=0.05,
        )

        current_stage_name = "chunking"
        try:
            total_steps = len(document_ids) * 3 + 2  # chunking, extraction, normalization per doc + candidates + relationships
            completed_steps = 0

            # ── 1. Document-Level Stages ──────────────────────────────
            for doc_idx, doc_id in enumerate(document_ids, 1):
                # A. Chunking
                current_stage_name = "chunking"
                self._update_job(
                    job_id,
                    stage="chunking",
                    completed_items=completed_steps,
                    total_items=total_steps,
                    progress=round(completed_steps / total_steps, 2),
                )
                chunker = LayoutAwareChunker()
                chunker.chunk_document(doc_id, force=(mode in ("reprocess", "full")))
                completed_steps += 1

                # B. Fact Extraction
                current_stage_name = "fact_extraction"
                self._update_job(
                    job_id,
                    stage="fact_extraction",
                    completed_items=completed_steps,
                    total_items=total_steps,
                    progress=round(completed_steps / total_steps, 2),
                )
                extractor = ExtractionService()
                await extractor.extract_document(doc_id, force=(mode in ("reprocess", "full")))
                completed_steps += 1

                # C. Normalization & Deduplication
                current_stage_name = "normalization"
                self._update_job(
                    job_id,
                    stage="normalization",
                    completed_items=completed_steps,
                    total_items=total_steps,
                    progress=round(completed_steps / total_steps, 2),
                )
                normalizer = NormalizationPipeline()
                normalizer.normalize_and_deduplicate_document(doc_id)
                completed_steps += 1

            # ── 2. Cross-Document Matching Stages ─────────────────────
            # D. Candidate Generation
            current_stage_name = "candidate_generation"
            self._update_job(
                job_id,
                stage="candidate_generation",
                completed_items=completed_steps,
                total_items=total_steps,
                progress=round(completed_steps / total_steps, 2),
            )
            candidate_gen = CandidateGenerator(db_path=self.db_path)
            candidate_gen.generate_candidates()
            completed_steps += 1

            # E. Relationship Reasoning
            current_stage_name = "relationship_reasoning"
            self._update_job(
                job_id,
                stage="relationship_reasoning",
                completed_items=completed_steps,
                total_items=total_steps,
                progress=round(completed_steps / total_steps, 2),
            )
            reasoner = RelationshipEngine(db_path=self.db_path)
            reasoner.evaluate_candidates(force=(mode in ("reprocess", "full")))
            completed_steps += 1

            # ── 3. Completed ──────────────────────────────────────────
            completed_now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self._update_job(
                job_id,
                status=JobStatus.COMPLETED.value,
                stage="completed",
                completed_items=total_steps,
                total_items=total_steps,
                progress=1.0,
                completed_at=completed_now,
            )
            logger.info("Job %s completed successfully", job_id)

        except Exception as e:
            logger.exception("Job %s failed at stage '%s' with error: %s", job_id, current_stage_name, e)
            self._update_job(
                job_id,
                status=JobStatus.FAILED.value,
                stage=current_stage_name,
                error_message=str(e),
                completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )

    def start_job(
        self,
        document_ids: list[str],
        mode: str = "full",
        job_id: Optional[str] = None,
    ) -> str:
        """Enqueue a new pipeline job and launch async execution."""
        jid = job_id or f"job_{uuid.uuid4().hex[:12]}"
        total_steps = len(document_ids) * 3 + 2
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """INSERT OR REPLACE INTO jobs (
                    id, job_type, document_ids_json, status, progress,
                    current_stage, total_items, completed_items, created_at, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    jid,
                    mode,
                    json.dumps(document_ids),
                    JobStatus.QUEUED.value,
                    0.0,
                    "queued",
                    total_steps,
                    0,
                    now_str,
                    now_str,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Launch background execution (asyncio task if loop running, else daemon thread)
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.run_pipeline(jid, document_ids, mode))
            self._running_tasks.add(task)
            task.add_done_callback(self._running_tasks.discard)
        except RuntimeError:
            import threading

            def _run():
                asyncio.run(self.run_pipeline(jid, document_ids, mode))

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

        return jid


# Global singleton instance
_runner: Optional[LocalJobRunner] = None


def get_job_runner() -> LocalJobRunner:
    """Return singleton instance of LocalJobRunner."""
    global _runner
    if _runner is None:
        _runner = LocalJobRunner()
    return _runner
