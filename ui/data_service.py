"""Data access service for Streamlit UI with direct SQLite querying and job execution."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import uuid
from typing import Any, Optional

import sys
from pathlib import Path

# Ensure project root is first in sys.path and remove 'ui' directory from sys.path
_UI_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _UI_DIR.parent
sys.path = [p for p in sys.path if Path(p).resolve() != _UI_DIR]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.db.database import get_connection
from app.models.schemas import DocumentStatus
from app.services.ingestion.document_ingestor import DocumentIngestor
from app.workers.job_runner import get_job_runner

logger = logging.getLogger(__name__)


class UIDataService:
    """Unified data layer providing reactive queries and background job control."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    # ── 1. Document Management ─────────────────────────────────────────

    def get_documents(
        self,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Fetch all documents with status and metadata."""
        conn = get_connection(self.db_path)
        try:
            sql = "SELECT * FROM documents WHERE 1=1"
            params: list = []
            if status:
                sql += " AND status = ?"
                params.append(status)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_document_count(self) -> int:
        """Return total count of ingested documents."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT COUNT(*) as c FROM documents").fetchone()
            return row["c"] if row else 0
        finally:
            conn.close()

    def upload_pdf_bytes(
        self,
        file_bytes: bytes,
        filename: str,
    ) -> tuple[dict[str, Any], bool]:
        """Ingest uploaded PDF bytes, checking SHA-256 duplicate detection.

        Returns (document_dict, is_new).
        """
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        conn = get_connection(self.db_path)
        try:
            existing = conn.execute(
                "SELECT * FROM documents WHERE sha256 = ?", (file_hash,)
            ).fetchone()
            if existing:
                return dict(existing), False
        finally:
            conn.close()

        ingestor = DocumentIngestor()
        result = ingestor.ingest_from_bytes(file_bytes, filename)
        conn = get_connection(self.db_path)
        try:
            doc = conn.execute("SELECT * FROM documents WHERE id = ?", (result.document_id,)).fetchone()
            return dict(doc), True
        finally:
            conn.close()

    # ── 2. Job Execution & Status ──────────────────────────────────────

    def start_pipeline_job(
        self,
        document_ids: list[str],
        mode: str = "full",
    ) -> str:
        """Enqueue an asynchronous pipeline execution job."""
        runner = get_job_runner()
        return runner.start_job(document_ids, mode=mode)

    def get_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch past and active jobs."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                if item.get("document_ids_json"):
                    try:
                        item["doc_ids"] = json.loads(item["document_ids_json"])
                    except Exception:
                        item["doc_ids"] = []
                else:
                    item["doc_ids"] = []
                results.append(item)
            return results
        finally:
            conn.close()

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Fetch single job status."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── 3. Knowledge Summary ───────────────────────────────────────────

    def get_knowledge_summary(self) -> dict[str, int]:
        """Aggregate counts across documents, facts, validations, and relationships."""
        conn = get_connection(self.db_path)
        try:
            doc_count = conn.execute("SELECT COUNT(*) as c FROM documents").fetchone()["c"]

            facts_row = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN validation_status = 'validated' THEN 1 ELSE 0 END) as validated,
                    SUM(CASE WHEN validation_status = 'warning' THEN 1 ELSE 0 END) as warning,
                    SUM(CASE WHEN validation_status = 'rejected' THEN 1 ELSE 0 END) as rejected
                   FROM facts"""
            ).fetchone()

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

            ent_count = conn.execute("SELECT COUNT(*) as c FROM entities").fetchone()["c"]

            return {
                "documents": doc_count,
                "facts": facts_row["total"] or 0,
                "validated_facts": facts_row["validated"] or 0,
                "warnings": facts_row["warning"] or 0,
                "rejected": facts_row["rejected"] or 0,
                "relationships": rel_row["total"] or 0,
                "corroborations": rel_row["corroborates"] or 0,
                "contradictions": rel_row["contradicts"] or 0,
                "reconciliations": rel_row["reconciles"] or 0,
                "uncertain": rel_row["uncertain"] or 0,
                "unrelated": rel_row["unrelated"] or 0,
                "entities": ent_count,
            }
        finally:
            conn.close()

    def get_entity_breakdown(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch resolved canonical entities with aliases."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """SELECT e.*, COUNT(f.id) as fact_count
                   FROM entities e
                   LEFT JOIN facts f ON e.id = f.entity_id
                   GROUP BY e.id
                   ORDER BY fact_count DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                aliases = conn.execute(
                    "SELECT alias FROM entity_aliases WHERE entity_id = ?", (item["id"],)
                ).fetchall()
                item["aliases"] = [a["alias"] for a in aliases]
                results.append(item)
            return results
        finally:
            conn.close()

    # ── 4. Facts Explorer ──────────────────────────────────────────────

    def get_facts(
        self,
        query_text: Optional[str] = None,
        document_id: Optional[str] = None,
        validation_status: Optional[str] = None,
        value_type: Optional[str] = None,
        min_confidence: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search and filter extracted facts with provenance metadata."""
        conn = get_connection(self.db_path)
        try:
            sql = """
                SELECT f.*, d.original_filename as document_name, e.canonical_name as canonical_entity
                FROM facts f
                LEFT JOIN documents d ON f.document_id = d.id
                LEFT JOIN entities e ON f.entity_id = e.id
                WHERE 1=1
            """
            params: list[Any] = []

            if query_text:
                q = f"%{query_text}%"
                sql += " AND (f.subject LIKE ? OR f.predicate LIKE ? OR f.value_text LIKE ? OR f.source_quote LIKE ?)"
                params.extend([q, q, q, q])

            if document_id:
                sql += " AND f.document_id = ?"
                params.append(document_id)

            if validation_status:
                sql += " AND f.validation_status = ?"
                params.append(validation_status.lower())

            if value_type:
                sql += " AND f.value_type = ?"
                params.append(value_type.lower())

            if min_confidence is not None:
                sql += " AND f.extraction_confidence >= ?"
                params.append(min_confidence)

            sql += " ORDER BY f.rowid DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── 5. Cross-Document Relationships ────────────────────────────────

    def get_relationships_enriched(
        self,
        rel_type: Optional[str] = None,
        sort_by: str = "confidence",
        search_query: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch relationships enriched with Fact A, Fact B, and source document metadata."""
        conn = get_connection(self.db_path)
        try:
            sql = """
                SELECT
                    r.*,
                    fa.subject as fa_subject,
                    fa.predicate as fa_predicate,
                    fa.value_text as fa_value,
                    fa.normalized_numeric_value as fa_norm_val,
                    fa.unit as fa_unit,
                    fa.time_text as fa_time,
                    fa.scope as fa_scope,
                    fa.geography as fa_geography,
                    fa.source_quote as fa_quote,
                    fa.source_page_start as fa_page,
                    fa.document_id as fa_doc_id,
                    da.original_filename as fa_doc_name,

                    fb.subject as fb_subject,
                    fb.predicate as fb_predicate,
                    fb.value_text as fb_value,
                    fb.normalized_numeric_value as fb_norm_val,
                    fb.unit as fb_unit,
                    fb.time_text as fb_time,
                    fb.scope as fb_scope,
                    fb.geography as fb_geography,
                    fb.source_quote as fb_quote,
                    fb.source_page_start as fb_page,
                    fb.document_id as fb_doc_id,
                    db.original_filename as fb_doc_name
                FROM relationships r
                JOIN facts fa ON r.fact_a_id = fa.id
                JOIN facts fb ON r.fact_b_id = fb.id
                LEFT JOIN documents da ON fa.document_id = da.id
                LEFT JOIN documents db ON fb.document_id = db.id
                WHERE 1=1
            """
            params: list[Any] = []

            if rel_type and rel_type.lower() != "all":
                sql += " AND r.relationship_type = ?"
                params.append(rel_type.lower())

            if search_query:
                sq = f"%{search_query}%"
                sql += """ AND (
                    r.explanation LIKE ? OR
                    fa.subject LIKE ? OR
                    fb.subject LIKE ? OR
                    fa.predicate LIKE ? OR
                    fb.predicate LIKE ? OR
                    da.original_filename LIKE ? OR
                    db.original_filename LIKE ?
                )"""
                params.extend([sq, sq, sq, sq, sq, sq, sq])

            if sort_by == "confidence":
                sql += " ORDER BY r.confidence DESC, r.created_at DESC LIMIT ?"
            else:
                sql += " ORDER BY r.created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                # Parse context comparison json if present
                if item.get("context_comparison_json"):
                    try:
                        item["context_comp"] = json.loads(item["context_comparison_json"])
                    except Exception:
                        item["context_comp"] = {}
                else:
                    item["context_comp"] = {}
                results.append(item)
            return results
        finally:
            conn.close()

    # ── 6. Failures & Uncertainty ──────────────────────────────────────

    def get_rejected_facts(self) -> list[dict[str, Any]]:
        """Fetch facts flagged as rejected during quote verification."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """SELECT f.*, d.original_filename as document_name
                   FROM facts f
                   LEFT JOIN documents d ON f.document_id = d.id
                   WHERE f.validation_status = 'rejected'
                   ORDER BY f.created_at DESC"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_warning_facts(self) -> list[dict[str, Any]]:
        """Fetch facts with validation warnings."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """SELECT f.*, d.original_filename as document_name
                   FROM facts f
                   LEFT JOIN documents d ON f.document_id = d.id
                   WHERE f.validation_status = 'warning'
                   ORDER BY f.created_at DESC"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_uncertain_relationships(self) -> list[dict[str, Any]]:
        """Fetch relationships classified as UNCERTAIN."""
        return self.get_relationships_enriched(rel_type="uncertain")

    def get_failed_jobs(self) -> list[dict[str, Any]]:
        """Fetch jobs that encountered errors."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = 'failed' ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── 7. Demo Data Seeder ───────────────────────────────────────────

    def seed_demo_dataset(self) -> None:
        """Seed a rich multi-document demonstration dataset matching the design mockup."""
        conn = get_connection(self.db_path)
        try:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            # 1. Documents
            doc_annual = "doc_demo_annual"
            doc_investor = "doc_demo_investor"
            doc_sustainability = "doc_demo_sustainability"

            docs = [
                (doc_annual, "annual_report.pdf", "annual_report.pdf", "hash_annual_1", 102400, 52, "Annual Report 2025", "uploaded", now),
                (doc_investor, "investor_report.pdf", "investor_report.pdf", "hash_investor_2", 84200, 24, "Q4 Investor Presentation", "uploaded", now),
                (doc_sustainability, "sustainability_report.pdf", "sustainability_report.pdf", "hash_sustain_3", 95300, 38, "Global Sustainability & ESG Report", "uploaded", now),
            ]
            conn.executemany(
                """INSERT OR REPLACE INTO documents (
                    id, filename, original_filename, sha256, file_size, page_count, title, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                docs,
            )

            # 2. Chunks (for foreign key integrity)
            chunks = [
                ("chk_1", doc_annual, 1, 1, 1, "[]", "1. Financials", "Sample text", 100, "chash_1", "completed"),
                ("chk_2", doc_investor, 1, 1, 1, "[]", "2. Q4 Highlights", "Sample text", 100, "chash_2", "completed"),
                ("chk_3", doc_sustainability, 1, 1, 1, "[]", "3. People & Planet", "Sample text", 100, "chash_3", "completed"),
            ]
            conn.executemany(
                """INSERT OR REPLACE INTO chunks (
                    id, document_id, sequence_index, start_page, end_page, block_ids_json, heading_path_json, text, token_count, content_hash, extraction_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                chunks,
            )

            # 3. Entities
            entities = [
                ("ent_acme", "Acme Corporation", "organization", 1.0, now),
                ("ent_ceo", "Jane Doe", "person", 1.0, now),
                ("ent_hq", "San Francisco, CA", "location", 1.0, now),
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO entities (id, canonical_name, entity_type, confidence, created_at) VALUES (?, ?, ?, ?, ?)",
                entities,
            )

            # 4. Facts
            # Pairs:
            # 1. RECONCILES: Revenue $12.5B (FY2025) vs $3.2B (Q4 FY2025)
            # 2. CORROBORATES: Headquarters San Francisco
            # 3. CONTRADICTS: Employee count mismatch 120,000 vs 95,000
            # 4. RECONCILES: Emissions Scope 1 vs Scope 2
            # 5. CORROBORATES: CEO name Jane Doe
            # 6. UNCERTAIN: R&D figures unclear
            facts = [
                # Fact A1: Revenue FY2025
                ("fact_rev_fy", doc_annual, "chk_1", "Acme Corporation", "revenue", "$12.5B", "currency", 12500000000.0, 12500000000.0, "USD", "USD", "FY2025", "consolidated", "Global", "Revenue for fiscal year 2025 reached $12.5B across all global operations.", 47, 47, 0.98, "validated", now),
                # Fact B1: Revenue Q4 FY2025
                ("fact_rev_q4", doc_investor, "chk_2", "Acme Corporation", "revenue", "$3.2B", "currency", 3200000000.0, 3200000000.0, "USD", "USD", "Q4 FY2025", "consolidated", "Global", "Fourth-quarter revenue reached $3.2B, driven by enterprise software growth.", 12, 12, 0.96, "validated", now),

                # Fact A2: Headquarters
                ("fact_hq_a", doc_annual, "chk_1", "Acme Corporation", "headquarters", "San Francisco, CA", "text", None, None, None, None, "FY2025", "corporate", "USA", "Acme Corporation is headquartered in San Francisco, CA.", 2, 2, 0.99, "validated", now),
                # Fact B2: Headquarters
                ("fact_hq_b", doc_investor, "chk_2", "Acme Corporation", "headquarters", "San Francisco, California", "text", None, None, None, None, "FY2025", "corporate", "USA", "Headquartered in San Francisco, California, the company operates in 30 countries.", 4, 4, 0.97, "validated", now),

                # Fact A3: Employee count
                ("fact_emp_a", doc_annual, "chk_1", "Acme Corporation", "headcount", "120,000 employees", "number", 120000.0, 120000.0, "employees", None, "FY2025", "worldwide", "Global", "Total full-time employee headcount stood at 120,000 worldwide at fiscal year-end.", 50, 50, 0.95, "validated", now),
                # Fact B3: Employee count mismatch
                ("fact_emp_b", doc_sustainability, "chk_3", "Acme Corporation", "headcount", "95,000 employees", "number", 95000.0, 95000.0, "employees", None, "FY2025", "worldwide", "Global", "As of FY2025 close, our global team comprised 95,000 total personnel.", 8, 8, 0.92, "validated", now),

                # Fact A4: Scope 1 Emissions
                ("fact_em_a", doc_sustainability, "chk_3", "Acme Corporation", "greenhouse gas emissions", "1.2M metric tons", "quantity", 1200000.0, 1200000.0, "metric tons", None, "FY2025", "Scope 1 Direct", "Global", "Scope 1 direct greenhouse gas emissions totaled 1.2M metric tons.", 19, 19, 0.94, "validated", now),
                # Fact B4: Total Emissions
                ("fact_em_b", doc_annual, "chk_1", "Acme Corporation", "greenhouse gas emissions", "3.8M metric tons", "quantity", 3800000.0, 3800000.0, "metric tons", None, "FY2025", "Consolidated (Scope 1+2)", "Global", "Consolidated greenhouse gas emissions reached 3.8M metric tons in FY2025.", 52, 52, 0.91, "validated", now),

                # Fact A5: CEO
                ("fact_ceo_a", doc_annual, "chk_1", "Acme Corporation", "chief executive officer", "Jane Doe", "text", None, None, None, None, "FY2025", "corporate", "Global", "Chief Executive Officer Jane Doe addressed stockholders during the annual meeting.", 3, 3, 0.99, "validated", now),
                # Fact B5: CEO
                ("fact_ceo_b", doc_investor, "chk_2", "Acme Corporation", "CEO", "Jane Doe", "text", None, None, None, None, "FY2025", "corporate", "Global", "Led by CEO Jane Doe, the leadership team outlined strategic milestones.", 2, 2, 0.98, "validated", now),

                # Fact A6: R&D
                ("fact_rd_a", doc_annual, "chk_1", "Acme Corporation", "R&D investment", "$1.8B", "currency", 1800000000.0, 1800000000.0, "USD", "USD", "FY2025", "unspecified", "Global", "Research and development expenditures were approximately $1.8B.", 35, 35, 0.72, "warning", now),
                # Fact B6: R&D
                ("fact_rd_b", doc_sustainability, "chk_3", "Acme Corporation", "R&D investment", "$600M", "currency", 600000000.0, 600000000.0, "USD", "USD", "FY2025", "green initiatives", "Global", "Green technology R&D investments amounted to $600M.", 14, 14, 0.68, "warning", now),

                # Quality audit facts (rejected / warning)
                ("fact_hallucinated", doc_annual, "chk_1", "Acme Corporation", "profit margin", "99%", "percentage", 99.0, 99.0, "%", None, "FY2025", "unsupported", "Global", "Profit margin was ninety-nine percent (hallucinated text not in document).", 1, 1, 0.30, "rejected", now),
            ]

            conn.executemany(
                """INSERT OR REPLACE INTO facts (
                    id, document_id, chunk_id, subject, predicate, value_text, value_type,
                    numeric_value, normalized_numeric_value, unit, currency, time_text,
                    scope, geography, source_quote, source_page_start, source_page_end,
                    extraction_confidence, validation_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                facts,
            )

            # 5. Relationships
            comp_rev = json.dumps([
                {"dimension": "Entity", "fact_a": "Acme Corporation", "fact_b": "Acme Corporation", "match": True},
                {"dimension": "Metric", "fact_a": "Revenue", "fact_b": "Revenue", "match": True},
                {"dimension": "Time Period", "fact_a": "FY2025", "fact_b": "Q4 FY2025", "match": False},
                {"dimension": "Geography", "fact_a": "Global", "fact_b": "Global", "match": True},
                {"dimension": "Unit/Currency", "fact_a": "USD", "fact_b": "USD", "match": True},
                {"dimension": "Scope", "fact_a": "Consolidated", "fact_b": "Consolidated", "match": True},
            ])

            comp_emp = json.dumps([
                {"dimension": "Entity", "fact_a": "Acme Corporation", "fact_b": "Acme Corporation", "match": True},
                {"dimension": "Metric", "fact_a": "Headcount", "fact_b": "Headcount", "match": True},
                {"dimension": "Time Period", "fact_a": "FY2025", "fact_b": "FY2025", "match": True},
                {"dimension": "Geography", "fact_a": "Global", "fact_b": "Global", "match": True},
                {"dimension": "Unit", "fact_a": "Employees", "fact_b": "Employees", "match": True},
                {"dimension": "Scope", "fact_a": "Worldwide", "fact_b": "Worldwide", "match": True},
            ])

            comp_hq = json.dumps([
                {"dimension": "Entity", "fact_a": "Acme Corporation", "fact_b": "Acme Corporation", "match": True},
                {"dimension": "Metric", "fact_a": "Headquarters", "fact_b": "Headquarters", "match": True},
                {"dimension": "Location", "fact_a": "San Francisco, CA", "fact_b": "San Francisco, California", "match": True},
            ])

            comp_em = json.dumps([
                {"dimension": "Entity", "fact_a": "Acme Corporation", "fact_b": "Acme Corporation", "match": True},
                {"dimension": "Metric", "fact_a": "Emissions", "fact_b": "Emissions", "match": True},
                {"dimension": "Scope", "fact_a": "Scope 1 Direct", "fact_b": "Consolidated Scope 1+2", "match": False},
            ])

            comp_rd = json.dumps([
                {"dimension": "Entity", "fact_a": "Acme Corporation", "fact_b": "Acme Corporation", "match": True},
                {"dimension": "Metric", "fact_a": "R&D", "fact_b": "R&D", "match": True},
                {"dimension": "Scope", "fact_a": "Unspecified Total", "fact_b": "Green Initiatives Only", "match": False},
            ])

            relationships = [
                (
                    "rel_demo_rev",
                    "fact_rev_fy",
                    "fact_rev_q4",
                    "reconciles",
                    0.94,
                    "time",
                    comp_rev,
                    "The revenue figures are different because they refer to different reporting periods. Fact A covers the full fiscal year 2025, while Fact B covers only Q4 FY2025, making the claims compatible rather than contradictory.",
                    "Revenue for fiscal year 2025 reached $12.5B across all global operations.",
                    "Fourth-quarter revenue reached $3.2B, driven by enterprise software growth.",
                    "v1.0",
                    now,
                ),
                (
                    "rel_demo_hq",
                    "fact_hq_a",
                    "fact_hq_b",
                    "corroborates",
                    0.92,
                    "value",
                    comp_hq,
                    "Both documents confirm the exact same corporate headquarters location in San Francisco, California.",
                    "Acme Corporation is headquartered in San Francisco, CA.",
                    "Headquartered in San Francisco, California, the company operates in 30 countries.",
                    "v1.0",
                    now,
                ),
                (
                    "rel_demo_emp",
                    "fact_emp_a",
                    "fact_emp_b",
                    "contradicts",
                    0.87,
                    "value",
                    comp_emp,
                    "Direct contradiction: Annual Report states 120,000 employees while the Sustainability Report states 95,000 employees for the exact same fiscal period (FY2025) and worldwide scope.",
                    "Total full-time employee headcount stood at 120,000 worldwide at fiscal year-end.",
                    "As of FY2025 close, our global team comprised 95,000 total personnel.",
                    "v1.0",
                    now,
                ),
                (
                    "rel_demo_em",
                    "fact_em_a",
                    "fact_em_b",
                    "reconciles",
                    0.85,
                    "scope",
                    comp_em,
                    "Emissions data varies because Fact A measures direct Scope 1 emissions (1.2M MT), whereas Fact B measures consolidated Scope 1 and Scope 2 emissions (3.8M MT).",
                    "Scope 1 direct greenhouse gas emissions totaled 1.2M metric tons.",
                    "Consolidated greenhouse gas emissions reached 3.8M metric tons in FY2025.",
                    "v1.0",
                    now,
                ),
                (
                    "rel_demo_ceo",
                    "fact_ceo_a",
                    "fact_ceo_b",
                    "corroborates",
                    0.82,
                    "value",
                    comp_hq,
                    "Both documents independently confirm Jane Doe as the Chief Executive Officer.",
                    "Chief Executive Officer Jane Doe addressed stockholders during the annual meeting.",
                    "Led by CEO Jane Doe, the leadership team outlined strategic milestones.",
                    "v1.0",
                    now,
                ),
                (
                    "rel_demo_rd",
                    "fact_rd_a",
                    "fact_rd_b",
                    "uncertain",
                    0.68,
                    "scope",
                    comp_rd,
                    "R&D investment figures are uncertain: Fact A provides total R&D ($1.8B) without breakdown, while Fact B reports green initiative R&D ($600M) without specifying if it is an inclusive subset.",
                    "Research and development expenditures were approximately $1.8B.",
                    "Green technology R&D investments amounted to $600M.",
                    "v1.0",
                    now,
                ),
            ]

            conn.executemany(
                """INSERT OR REPLACE INTO relationships (
                    id, fact_a_id, fact_b_id, relationship_type, confidence, primary_dimension,
                    context_comparison_json, explanation, evidence_fact_a, evidence_fact_b,
                    reasoning_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                relationships,
            )

            # 6. Completed Job record
            conn.execute(
                """INSERT OR REPLACE INTO jobs (
                    id, job_type, document_ids_json, status, progress, current_stage, total_items, completed_items, created_at, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "job_demo_completed",
                    "full",
                    json.dumps([doc_annual, doc_investor, doc_sustainability]),
                    "completed",
                    1.0,
                    "completed",
                    11,
                    11,
                    now,
                    now,
                    now,
                ),
            )

            conn.commit()
            logger.info("Demo dataset successfully seeded!")
        finally:
            conn.close()


# Singleton instance
_service: Optional[UIDataService] = None


def get_data_service(db_path: Optional[str] = None) -> UIDataService:
    """Return singleton instance of UIDataService."""
    global _service
    if _service is None or (_service.db_path != db_path):
        _service = UIDataService(db_path)
    return _service
