"""Comprehensive test suite for Phase 9 — FastAPI Endpoints & Asynchronous Job Runner."""

from __future__ import annotations

import io
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_connection
from app.models.schemas import (
    CandidateStatus,
    DocumentStatus,
    EntityType,
    PrimaryDimension,
    RelationshipType,
    ValidationStatus,
    ValueType,
)
from app.services.extraction.models import ExtractedFact, ExtractionResult
from app.workers.job_runner import LocalJobRunner, get_job_runner
from tests.fixtures_pdf import create_sample_pdf


# ── 1. Health Endpoint Tests ─────────────────────────────────────────


def test_v1_health_endpoint(client: TestClient):
    """GET /health must return 200 OK with version, db status, and document count."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert data["database"] == "connected"
    assert "documents_count" in data


# ── 2. Documents Endpoints Tests ─────────────────────────────────────


def test_v1_upload_multiple_documents(client: TestClient):
    """POST /v1/documents must support multi-file PDF uploads."""
    pdf1 = create_sample_pdf()
    pdf2 = create_sample_pdf()

    files = [
        ("files", ("annual_report_2024.pdf", io.BytesIO(pdf1), "application/pdf")),
        ("files", ("annual_report_2025.pdf", io.BytesIO(pdf2), "application/pdf")),
    ]

    resp = client.post("/v1/documents", files=files)
    assert resp.status_code == 201
    data = resp.json()
    assert "documents" in data
    # Because both have identical content, the second will reuse the existing one or both will be valid items
    assert len(data["documents"]) == 2
    for doc in data["documents"]:
        assert doc["id"] and isinstance(doc["id"], str)
        assert doc["sha256"] is not None
        assert doc["status"] == "uploaded"


def test_v1_upload_deduplication_by_sha256(client: TestClient, sample_pdf_bytes: bytes):
    """Repeated submission of identical PDF must reuse existing document without re-running ingestion."""
    # First upload
    files1 = [("files", ("doc_a.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    resp1 = client.post("/v1/documents", files=files1)
    assert resp1.status_code == 201
    doc_id_1 = resp1.json()["documents"][0]["id"]

    # Second upload with same PDF bytes but different filename
    files2 = [("files", ("doc_b.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    resp2 = client.post("/v1/documents", files=files2)
    assert resp2.status_code == 201
    doc_id_2 = resp2.json()["documents"][0]["id"]

    # Must reuse the same document ID
    assert doc_id_1 == doc_id_2

    # Database documents count must be 1
    conn = get_connection()
    try:
        cnt = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
        assert cnt == 1
    finally:
        conn.close()


def test_v1_upload_rejects_non_pdf(client: TestClient):
    """POST /v1/documents rejects non-PDF files."""
    files = [("files", ("notes.txt", io.BytesIO(b"Hello world"), "text/plain"))]
    resp = client.post("/v1/documents", files=files)
    assert resp.status_code == 400
    assert "not a PDF" in resp.json()["detail"]


def test_v1_upload_rejects_corrupt_magic_bytes(client: TestClient):
    """POST /v1/documents rejects files without %PDF header signature."""
    files = [("files", ("corrupted.pdf", io.BytesIO(b"NOT A REAL PDF FILE"), "application/pdf"))]
    resp = client.post("/v1/documents", files=files)
    assert resp.status_code == 400
    assert "valid PDF header" in resp.json()["detail"]


def test_v1_get_documents_and_pages(client: TestClient, sample_pdf_bytes: bytes):
    """GET /v1/documents, GET /v1/documents/{id}, and GET /v1/documents/{id}/pages."""
    # Ingest document
    files = [("files", ("quarterly_2024.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    upload_resp = client.post("/v1/documents", files=files)
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["documents"][0]["id"]

    # List documents
    list_resp = client.get("/v1/documents?limit=10&offset=0")
    assert list_resp.status_code == 200
    docs = list_resp.json()
    assert len(docs) >= 1
    assert docs[0]["id"] == doc_id

    # Filter documents by status
    filter_resp = client.get("/v1/documents?status=uploaded")
    assert filter_resp.status_code == 200
    assert any(d["id"] == doc_id for d in filter_resp.json())

    # Get single document
    get_resp = client.get(f"/v1/documents/{doc_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == doc_id
    assert get_resp.json()["page_count"] == 4

    # Get document pages
    pages_resp = client.get(f"/v1/documents/{doc_id}/pages")
    assert pages_resp.status_code == 200
    pages = pages_resp.json()
    assert len(pages) == 4
    for idx, page in enumerate(pages):
        assert page["page_number"] == idx + 1
        assert page["document_id"] == doc_id
        assert page["raw_text"] is not None

    # Nonexistent document returns 404
    assert client.get("/v1/documents/doc_nonexistent").status_code == 404
    assert client.get("/v1/documents/doc_nonexistent/pages").status_code == 404


# ── 3. Jobs Endpoints Tests ──────────────────────────────────────────


def test_v1_create_job_and_status(client: TestClient, sample_pdf_bytes: bytes):
    """POST /v1/jobs returns 202 Accepted with job ID, and GET /v1/jobs/{job_id} returns status."""
    # Ingest document
    files = [("files", ("report.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    upload_resp = client.post("/v1/documents", files=files)
    doc_id = upload_resp.json()["documents"][0]["id"]

    # Enqueue job
    job_payload = {
        "document_ids": [doc_id],
        "mode": "full",
    }
    resp = client.post("/v1/jobs", json=job_payload)
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "queued"
    job_id = data["job_id"]

    # Query job status
    status_resp = client.get(f"/v1/jobs/{job_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["id"] == job_id
    assert status_data["status"] in ("queued", "running", "completed")
    assert "progress" in status_data
    assert "stage" in status_data

    # Query invalid job ID
    assert client.get("/v1/jobs/job_unknown").status_code == 404


def test_v1_create_job_validation_errors(client: TestClient):
    """POST /v1/jobs validates empty document IDs and nonexistent IDs."""
    # Empty document list
    resp1 = client.post("/v1/jobs", json={"document_ids": []})
    assert resp1.status_code == 400

    # Nonexistent document ID
    resp2 = client.post("/v1/jobs", json={"document_ids": ["doc_does_not_exist"]})
    assert resp2.status_code == 404
    assert "not found" in resp2.json()["detail"]


# ── 4. Facts Endpoints Tests ─────────────────────────────────────────


def test_v1_facts_endpoints(client: TestClient, sample_pdf_bytes: bytes):
    """GET /v1/facts and GET /v1/facts/{id} with multi-attribute filtering."""
    # Ingest a document
    files = [("files", ("facts_doc.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    upload_resp = client.post("/v1/documents", files=files)
    doc_id = upload_resp.json()["documents"][0]["id"]

    # Chunk the document so valid chunks exist
    from app.services.ingestion.chunker import LayoutAwareChunker
    chunks = LayoutAwareChunker().chunk_document(doc_id)
    chunk_id = chunks[0].id

    # Insert test facts and entity directly into DB
    conn = get_connection()
    fact_id_1 = f"fact_{uuid.uuid4().hex[:12]}"
    fact_id_2 = f"fact_{uuid.uuid4().hex[:12]}"
    ent_id = f"ent_{uuid.uuid4().hex[:8]}"

    try:
        conn.execute(
            """INSERT INTO entities (id, canonical_name, entity_type, confidence)
               VALUES (?, ?, ?, ?)""",
            (ent_id, "Acme Corp", EntityType.ORGANIZATION.value, 1.0),
        )
        conn.execute(
            """INSERT INTO facts (
                id, document_id, chunk_id, subject, entity_id, predicate, value_text,
                value_type, numeric_value, normalized_numeric_value, unit,
                source_quote, source_page_start, source_page_end,
                extraction_confidence, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fact_id_1,
                doc_id,
                chunk_id,
                "Acme Corp",
                ent_id,
                "revenue",
                "$50 million",
                ValueType.CURRENCY.value,
                50000000.0,
                50000000.0,
                "USD",
                "Acme Corp generated $50 million in revenue.",
                1,
                1,
                0.95,
                ValidationStatus.VALIDATED.value,
            ),
        )
        conn.execute(
            """INSERT INTO facts (
                id, document_id, chunk_id, subject, predicate, value_text,
                value_type, numeric_value, normalized_numeric_value, unit,
                source_quote, source_page_start, source_page_end,
                extraction_confidence, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fact_id_2,
                doc_id,
                chunk_id,
                "Beta LLC",
                "headcount",
                "250 employees",
                ValueType.NUMBER.value,
                250.0,
                250.0,
                "employees",
                "Beta LLC employed 250 employees.",
                2,
                2,
                0.80,
                ValidationStatus.WARNING.value,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Query all facts
    resp = client.get("/v1/facts")
    assert resp.status_code == 200
    facts = resp.json()
    assert len(facts) >= 2

    # Filter by entity
    resp_entity = client.get("/v1/facts?entity=Acme")
    assert resp_entity.status_code == 200
    assert len(resp_entity.json()) == 1
    assert resp_entity.json()[0]["id"] == fact_id_1

    # Filter by predicate
    resp_pred = client.get("/v1/facts?predicate=headcount")
    assert resp_pred.status_code == 200
    assert len(resp_pred.json()) == 1
    assert resp_pred.json()[0]["id"] == fact_id_2

    # Filter by validation_status
    resp_val = client.get("/v1/facts?validation_status=validated")
    assert resp_val.status_code == 200
    assert all(f["validation_status"] == "validated" for f in resp_val.json())

    # Filter by min_confidence
    resp_conf = client.get("/v1/facts?min_confidence=0.90")
    assert resp_conf.status_code == 200
    assert all(f["extraction_confidence"] >= 0.90 for f in resp_conf.json())

    # Get single fact with complete provenance
    resp_single = client.get(f"/v1/facts/{fact_id_1}")
    assert resp_single.status_code == 200
    fact_data = resp_single.json()
    assert fact_data["id"] == fact_id_1
    assert fact_data["source_quote"] == "Acme Corp generated $50 million in revenue."
    assert fact_data["source_page_start"] == 1
    assert fact_data["normalized_numeric_value"] == 50000000.0

    # Nonexistent fact returns 404
    assert client.get("/v1/facts/fact_nonexistent").status_code == 404


# ── 5. Relationships Endpoints Tests ─────────────────────────────────


def test_v1_relationships_endpoints(client: TestClient, sample_pdf_bytes: bytes):
    """GET /v1/relationships and GET /v1/relationships/{id} with filtering."""
    # Ingest document
    files = [("files", ("rel_doc.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    upload_resp = client.post("/v1/documents", files=files)
    doc_id = upload_resp.json()["documents"][0]["id"]

    # Chunk document first
    from app.services.ingestion.chunker import LayoutAwareChunker
    chunks = LayoutAwareChunker().chunk_document(doc_id)
    chunk_id = chunks[0].id

    # Insert two facts and a relationship
    f1_id = f"fact_{uuid.uuid4().hex[:12]}"
    f2_id = f"fact_{uuid.uuid4().hex[:12]}"
    rel_id = f"rel_{uuid.uuid4().hex[:12]}"

    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO facts (
                id, document_id, chunk_id, subject, predicate, value_text, value_type,
                source_quote, source_page_start, source_page_end
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f1_id, doc_id, chunk_id, "Acme", "revenue", "$10M", "currency", "Quote 1", 1, 1),
        )
        conn.execute(
            """INSERT INTO facts (
                id, document_id, chunk_id, subject, predicate, value_text, value_type,
                source_quote, source_page_start, source_page_end
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f2_id, doc_id, chunk_id, "Acme", "revenue", "$10M", "currency", "Quote 2", 2, 2),
        )
        conn.execute(
            """INSERT INTO relationships (
                id, fact_a_id, fact_b_id, relationship_type, confidence,
                primary_dimension, explanation, evidence_fact_a, evidence_fact_b
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rel_id,
                f1_id,
                f2_id,
                RelationshipType.CORROBORATES.value,
                0.95,
                PrimaryDimension.VALUE.value,
                "Both facts report exactly $10M revenue.",
                "Quote 1",
                "Quote 2",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Query relationships
    resp = client.get("/v1/relationships")
    assert resp.status_code == 200
    rels = resp.json()
    assert len(rels) >= 1

    # Filter by type
    resp_type = client.get("/v1/relationships?type=corroborates")
    assert resp_type.status_code == 200
    assert all(r["relationship_type"] == "corroborates" for r in resp_type.json())

    # Filter by fact_id
    resp_fact = client.get(f"/v1/relationships?fact_id={f1_id}")
    assert resp_fact.status_code == 200
    assert len(resp_fact.json()) == 1

    # Filter by primary_dimension
    resp_dim = client.get("/v1/relationships?primary_dimension=value")
    assert resp_dim.status_code == 200
    assert len(resp_dim.json()) == 1

    # Filter by confidence
    resp_conf = client.get("/v1/relationships?confidence=0.90")
    assert resp_conf.status_code == 200
    assert len(resp_conf.json()) == 1

    # Get single relationship
    single_resp = client.get(f"/v1/relationships/{rel_id}")
    assert single_resp.status_code == 200
    rel_data = single_resp.json()
    assert rel_data["id"] == rel_id
    assert rel_data["relationship_type"] == "corroborates"
    assert rel_data["evidence_fact_a"] == "Quote 1"

    # Nonexistent relationship returns 404
    assert client.get("/v1/relationships/rel_unknown").status_code == 404


# ── 6. Knowledge Summary Endpoint Tests ──────────────────────────────


def test_v1_knowledge_summary(client: TestClient, sample_pdf_bytes: bytes):
    """GET /v1/knowledge/summary aggregates counts accurately across the knowledge layer."""
    # Initial summary
    resp0 = client.get("/v1/knowledge/summary")
    assert resp0.status_code == 200
    summary0 = resp0.json()
    assert "documents" in summary0
    assert "facts" in summary0
    assert "relationships" in summary0
    assert "entities" in summary0

    # Ingest document
    files = [("files", ("sum_doc.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    upload_resp = client.post("/v1/documents", files=files)
    doc_id = upload_resp.json()["documents"][0]["id"]

    # Chunk document first
    from app.services.ingestion.chunker import LayoutAwareChunker
    chunks = LayoutAwareChunker().chunk_document(doc_id)
    chunk_id = chunks[0].id

    # Insert test entities, facts, and relationships
    conn = get_connection()
    f1 = f"f1_{uuid.uuid4().hex[:6]}"
    f2 = f"f2_{uuid.uuid4().hex[:6]}"
    try:
        conn.execute("INSERT INTO entities (id, canonical_name) VALUES (?, ?)", ("ent_sum_1", "Test Entity"))
        conn.execute(
            """INSERT INTO facts (
                id, document_id, chunk_id, subject, predicate, value_text, value_type,
                source_quote, source_page_start, source_page_end, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f1, doc_id, chunk_id, "Test Entity", "metric", "100", "number", "quote", 1, 1, "validated"),
        )
        conn.execute(
            """INSERT INTO facts (
                id, document_id, chunk_id, subject, predicate, value_text, value_type,
                source_quote, source_page_start, source_page_end, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f2, doc_id, chunk_id, "Test Entity", "metric", "100", "number", "quote", 1, 1, "warning"),
        )
        conn.execute(
            """INSERT INTO relationships (
                id, fact_a_id, fact_b_id, relationship_type, confidence, explanation
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            ("r_sum_1", f1, f2, "corroborates", 0.9, "Corroboration summary"),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/v1/knowledge/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["documents"] >= 1
    assert summary["facts"] >= 2
    assert summary["validated_facts"] >= 1
    assert summary["warnings"] >= 1
    assert summary["relationships"] >= 1
    assert summary["corroborations"] >= 1
    assert summary["entities"] >= 1


# ── 7. Reprocessing Endpoints Tests ──────────────────────────────────


def test_v1_reprocess_endpoints(client: TestClient, sample_pdf_bytes: bytes):
    """POST /v1/reprocess/{document_id} and POST /v1/reprocess/{job_id} return 202 Accepted."""
    # Ingest document
    files = [("files", ("rep_doc.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    upload_resp = client.post("/v1/documents", files=files)
    doc_id = upload_resp.json()["documents"][0]["id"]

    # 1. Reprocess by document_id
    resp_doc = client.post(f"/v1/reprocess/{doc_id}")
    assert resp_doc.status_code == 202
    job_1 = resp_doc.json()["job_id"]
    assert job_1.startswith("job_")

    # 2. Reprocess by job_id
    resp_job = client.post(f"/v1/reprocess/{job_1}")
    assert resp_job.status_code == 202
    job_2 = resp_job.json()["job_id"]
    assert job_2.startswith("job_")
    assert job_2 != job_1

    # 3. Reprocess with invalid ID returns 404
    resp_invalid = client.post("/v1/reprocess/totally_invalid_id")
    assert resp_invalid.status_code == 404
    assert "matches neither" in resp_invalid.json()["detail"]


# ── 8. Local Job Runner Execution Test ───────────────────────────────


@pytest.mark.asyncio
async def test_local_job_runner_full_pipeline(sample_pdf_bytes: bytes):
    """Verify that LocalJobRunner executes through stages and updates status to completed."""
    # Initialize database tables
    from app.db.database import init_db
    init_db()

    # Ingest document
    from app.services.ingestion.document_ingestor import DocumentIngestor
    ingestor = DocumentIngestor()
    result = ingestor.ingest_from_bytes(sample_pdf_bytes, "pipeline_test.pdf")
    doc_id = result.document_id

    # Mock the ExtractionService to avoid OpenAI API calls
    with patch("app.workers.job_runner.ExtractionService.extract_document", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = []

        runner = LocalJobRunner()
        job_id = f"test_job_{uuid.uuid4().hex[:8]}"

        # Insert initial job row as start_job would do
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO jobs (
                    id, job_type, document_ids_json, status, progress, current_stage
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (job_id, "full", json.dumps([doc_id]), "queued", 0.0, "queued"),
            )
            conn.commit()
        finally:
            conn.close()

        # Directly run the pipeline coroutine
        await runner.run_pipeline(job_id, [doc_id], mode="full")

        job = runner.get_job(job_id)
        assert job is not None
        assert job.status.value == "completed"
        assert job.progress == 1.0
        assert job.current_stage == "completed"
        assert job.completed_at is not None
