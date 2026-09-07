"""Comprehensive test suite for Phase 5 — Structured LLM Fact Extraction."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_connection, init_db
from app.models.schemas import FactSchema, ValidationStatus, ValueType
from app.services.extraction.models import ExtractedFact, ExtractionResult, PromptVersion
from app.services.extraction.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_messages
from app.services.extraction.service import (
    ExtractionService,
    MockExtractionProvider,
)
from app.services.extraction.verifier import EvidenceVerifier, VerificationResult
from app.services.ingestion.chunker import LayoutAwareChunker
from app.services.ingestion.document_ingestor import DocumentIngestor
from tests.fixtures_pdf import create_sample_pdf


@pytest.fixture
def chunked_doc_id(sample_pdf_bytes: bytes) -> str:
    """Fixture that ingests and chunks a sample PDF, returning document ID."""
    init_db()
    ingestor = DocumentIngestor()
    result = ingestor.ingest_from_bytes(sample_pdf_bytes, "extraction_test.pdf")
    doc_id = result.document_id

    chunker = LayoutAwareChunker(min_tokens=20, max_tokens=100, overlap_tokens=10)
    chunker.chunk_document(doc_id, force=True)
    return doc_id


# ── 1. Model & Prompt Structure Tests ────────────────────────────────


def test_extracted_fact_model_separation():
    """Verify ExtractedFact strictly separates explicit source text from normalized interpretation

    and does NOT contain page numbers.
    """
    fact = ExtractedFact(
        source_quote="Acme Corporation achieved revenue of $120 million in FY2025.",
        subject_mention="Acme Corporation",
        predicate_mention="revenue",
        value_text="$120 million",
        subject="Acme Corporation",
        predicate="revenue",
        value_type=ValueType.CURRENCY,
        numeric_value=120000000.0,
        unit="USD",
        currency="USD",
        time_text="FY2025",
        scope="consolidated",
        confidence=0.98,
    )

    assert fact.source_quote == "Acme Corporation achieved revenue of $120 million in FY2025."
    assert fact.value_text == "$120 million"
    assert fact.numeric_value == 120000000.0
    assert not hasattr(fact, "page_number"), "Page number must NOT be in ExtractedFact (application-resolved)"
    assert not hasattr(fact, "source_page"), "Source page must NOT be in ExtractedFact (application-resolved)"


def test_extraction_system_prompt_content():
    """Verify system prompt enforces strict evidence rules."""
    assert "Only extract facts directly supported by the supplied text." in EXTRACTION_SYSTEM_PROMPT
    assert "preserve the source wording;" in EXTRACTION_SYSTEM_PROMPT
    assert "do not invent evidence." in EXTRACTION_SYSTEM_PROMPT
    assert "do not infer unsupported facts;" in EXTRACTION_SYSTEM_PROMPT

    messages = build_extraction_messages("Sample text", ["1. Introduction"])
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "Section Context: 1. Introduction" in messages[1]["content"]


# ── 2. Evidence Verification Guardrail Tests ─────────────────────────


def test_verifier_exact_quote_match():
    """Verify that an exact verbatim quote is validated and mapped to block and page."""
    verifier = EvidenceVerifier()
    chunk_text = "Acme Corporation achieved revenue of $120 million in FY2025. Operating margin was 22%."
    blocks = [
        {"id": "b1", "text": "Acme Corporation achieved revenue of $120 million in FY2025.", "page_number": 1},
        {"id": "b2", "text": "Operating margin was 22%.", "page_number": 1},
    ]

    res = verifier.verify(
        source_quote="Acme Corporation achieved revenue of $120 million in FY2025.",
        chunk_text=chunk_text,
        chunk_start_page=1,
        chunk_end_page=1,
        blocks=blocks,
    )

    assert res.status == ValidationStatus.VALIDATED
    assert res.start_page == 1
    assert res.end_page == 1
    assert res.block_ids == ["b1"]
    assert len(res.notes) == 0


def test_verifier_punctuation_minor_difference_warning():
    """Verify that minor punctuation differences yield WARNING status with descriptive note."""
    verifier = EvidenceVerifier()
    chunk_text = 'The company stated: "operating margin reached 22 percent."'
    blocks = [{"id": "b1", "text": 'The company stated: "operating margin reached 22 percent."', "page_number": 2}]

    # Quote has different quotes/dashes/spacing
    quote = "The company stated - 'operating margin reached 22 percent.'"

    res = verifier.verify(
        source_quote=quote,
        chunk_text=chunk_text,
        chunk_start_page=2,
        chunk_end_page=2,
        blocks=blocks,
    )

    assert res.status == ValidationStatus.WARNING
    assert "punctuation" in res.notes[0].lower() or "formatting" in res.notes[0].lower()
    assert res.block_ids == ["b1"]


def test_verifier_hallucinated_quote_rejected():
    """Verify that a fabricated or unsupported quote is firmly REJECTED and block_ids emptied."""
    verifier = EvidenceVerifier()
    chunk_text = "Acme Corporation achieved revenue of $120 million in FY2025."
    blocks = [{"id": "b1", "text": "Acme Corporation achieved revenue of $120 million in FY2025.", "page_number": 1}]

    res = verifier.verify(
        source_quote="CEO Jane Doe announced record dividend payments of $5 per share.",
        chunk_text=chunk_text,
        chunk_start_page=1,
        chunk_end_page=1,
        blocks=blocks,
    )

    assert res.status == ValidationStatus.REJECTED
    assert res.block_ids == []
    assert any("rejected" in n.lower() or "not found" in n.lower() for n in res.notes)


# ── 3. ExtractionService with Mock Provider (Offline Execution) ───────


@pytest.mark.asyncio
async def test_extraction_service_end_to_end(chunked_doc_id: str):
    """Test full document fact extraction with MockExtractionProvider and SQLite persistence."""
    mock_facts = [
        ExtractedFact(
            source_quote="Acme Corporation achieved revenue of $120 million in FY2025.",
            subject_mention="Acme Corporation",
            predicate_mention="revenue",
            value_text="$120 million",
            subject="Acme Corporation",
            predicate="revenue",
            value_type=ValueType.CURRENCY,
            numeric_value=120000000.0,
            currency="USD",
            time_text="FY2025",
            confidence=0.99,
        ),
        ExtractedFact(
            source_quote="Operating margin improved to 22 percent across all product divisions.",
            subject_mention="all product divisions",
            predicate_mention="Operating margin",
            value_text="22 percent",
            subject="Acme Corporation",
            predicate="operating_margin",
            value_type=ValueType.PERCENTAGE,
            numeric_value=0.22,
            confidence=0.95,
        ),
    ]

    mock_provider = MockExtractionProvider(
        mock_result=ExtractionResult(facts=mock_facts, extraction_notes=["Extracted 2 test facts."])
    )

    service = ExtractionService(provider=mock_provider, max_concurrency=2)
    facts = await service.extract_document(chunked_doc_id, force=True)

    assert len(facts) >= 2
    assert mock_provider.call_count > 0

    # Verify DB persistence
    conn = get_connection()
    try:
        db_facts = conn.execute(
            "SELECT * FROM facts WHERE document_id = ?", (chunked_doc_id,)
        ).fetchall()
        assert len(db_facts) == len(facts)

        first_fact = db_facts[0]
        assert first_fact["subject"] == "Acme Corporation"
        assert first_fact["predicate"] in ["revenue", "operating_margin"]
        assert first_fact["validation_status"] == "validated"
        assert first_fact["source_page_start"] == 1

        # Check chunks updated to completed
        chunk_statuses = conn.execute(
            "SELECT extraction_status FROM chunks WHERE document_id = ?", (chunked_doc_id,)
        ).fetchall()
        assert all(r["extraction_status"] == "completed" for r in chunk_statuses)
    finally:
        conn.close()


# ── 4. Caching Tier Tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extraction_caching_behavior(chunked_doc_id: str):
    """Verify that subsequent extraction runs hit SQLite llm_cache and avoid re-calling provider."""
    mock_facts = [
        ExtractedFact(
            source_quote="Acme Corporation achieved revenue of $120 million in FY2025.",
            subject_mention="Acme Corporation",
            predicate_mention="revenue",
            value_text="$120 million",
            subject="Acme Corporation",
            predicate="revenue",
            confidence=0.99,
        )
    ]
    mock_provider = MockExtractionProvider(
        mock_result=ExtractionResult(facts=mock_facts)
    )

    # First run: populate cache
    service = ExtractionService(provider=mock_provider, prompt_version="v1")
    await service.extract_document(chunked_doc_id, force=True)
    initial_calls = mock_provider.call_count
    assert initial_calls > 0

    # Second run with force=True (forces re-evaluation of chunks, but LLM calls should hit cache)
    service_2 = ExtractionService(provider=mock_provider, prompt_version="v1")
    await service_2.extract_document(chunked_doc_id, force=True)

    # Provider call count should NOT increase due to cache hits
    assert mock_provider.call_count == initial_calls, "LLM provider should not be called when cache hits"

    # Third run with different prompt version: must invalidate cache and call provider
    service_v2 = ExtractionService(provider=mock_provider, prompt_version="v2")
    await service_v2.extract_document(chunked_doc_id, force=True)
    assert mock_provider.call_count > initial_calls, "New prompt version must bypass old cache"


# ── 5. Concurrency & Retry Behavior ───────────────────────────────────


@pytest.mark.asyncio
async def test_extraction_retries_transient_failures():
    """Verify that transient exceptions are retried with exponential backoff."""
    attempt_count = 0

    def faulty_handler(messages: list[dict[str, str]], model: str) -> ExtractionResult:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            # Simulate transient timeout or rate limit
            raise ConnectionError("Transient network reset")
        return ExtractionResult(
            facts=[
                ExtractedFact(
                    source_quote="Recovered text after retry.",
                    subject_mention="System",
                    predicate_mention="recovery",
                    value_text="success",
                    subject="System",
                    predicate="recovery_status",
                    confidence=1.0,
                )
            ]
        )

    provider = MockExtractionProvider(handler=faulty_handler)
    service = ExtractionService(provider=provider)

    result = await service._call_with_retry(
        messages=[{"role": "user", "content": "test"}],
        max_retries=3,
        initial_delay=0.01,
        backoff_factor=1.5,
    )

    assert attempt_count == 3
    assert len(result.facts) == 1
    assert result.facts[0].value_text == "success"


@pytest.mark.asyncio
async def test_bounded_concurrency_semaphore(chunked_doc_id: str):
    """Verify that active concurrent LLM tasks never exceed semaphore capacity."""
    current_concurrency = 0
    max_observed_concurrency = 0

    def concurrency_tracking_handler(messages: list[dict[str, str]], model: str) -> ExtractionResult:
        nonlocal current_concurrency, max_observed_concurrency
        current_concurrency += 1
        if current_concurrency > max_observed_concurrency:
            max_observed_concurrency = current_concurrency
        # Short sleep to allow potential concurrency pile-up
        import time
        time.sleep(0.02)
        current_concurrency -= 1
        return ExtractionResult(facts=[])

    provider = MockExtractionProvider(handler=concurrency_tracking_handler)
    service = ExtractionService(provider=provider, max_concurrency=2)

    await service.extract_document(chunked_doc_id, force=True)
    assert max_observed_concurrency <= 2


# ── 6. API Facts and Extract Endpoints Tests ──────────────────────────


def test_api_facts_query_and_filtering(client: TestClient, sample_pdf_bytes: bytes):
    """Test GET /api/facts with filtering by document_id, validation_status, etc."""
    init_db()

    # 1. Upload & chunk document
    res_up = client.post(
        "/api/documents/upload",
        files={"file": ("facts_test.pdf", sample_pdf_bytes, "application/pdf")},
    )
    doc_id = res_up.json()["id"]
    chunk_res = client.post(f"/api/documents/{doc_id}/chunk")
    chunks = chunk_res.json()
    assert len(chunks) > 0
    chunk_id = chunks[0]["id"]

    # 2. Insert mock facts into database directly
    conn = get_connection()
    fact_id = "fact-test-uuid-1"
    conn.execute(
        """INSERT INTO facts (
            id, document_id, chunk_id, subject, predicate, value_text,
            source_quote, source_page_start, source_page_end, validation_status,
            extraction_confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fact_id, doc_id, chunk_id, "Acme Corporation", "revenue",
            "$120M", "revenue of $120M", 1, 1, "validated", 0.95,
        ),
    )
    conn.commit()
    conn.close()

    # 3. Query GET /api/facts
    res_facts = client.get(f"/api/facts?document_id={doc_id}&validation_status=validated")
    assert res_facts.status_code == 200
    facts = res_facts.json()
    assert len(facts) == 1
    assert facts[0]["id"] == fact_id
    assert facts[0]["subject"] == "Acme Corporation"
    assert facts[0]["numeric_value"] is None

    # 4. Query GET /api/facts/{id}
    res_single = client.get(f"/api/facts/{fact_id}")
    assert res_single.status_code == 200
    assert res_single.json()["id"] == fact_id

    # 5. Nonexistent fact 404
    res_404 = client.get("/api/facts/nonexistent-fact-uuid")
    assert res_404.status_code == 404
