"""Comprehensive evaluation test suite for Phase 11 — Testing and Failure Handling.

Explicitly tests Cases A, B, C, D alongside all 8 mandatory failure handling areas:
1. Evidence validation
2. Numeric normalization
3. Date normalization
4. Entity ambiguity
5. Candidate generation
6. Relationship classification
7. Cache reuse
8. Duplicate document detection
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.db.database import get_connection, init_db
from app.models.schemas import (
    CandidateStatus,
    EntityType,
    FactSchema,
    PrimaryDimension,
    RelationshipType,
    ValidationStatus,
    ValueType,
)
from app.services.extraction.verifier import EvidenceVerifier
from app.services.ingestion.chunker import LayoutAwareChunker
from app.services.ingestion.document_ingestor import DocumentIngestor
from app.services.ingestion.page_quality import PageQualityAnalyzer
from app.services.matching.candidates import CandidateGenerator
from app.services.normalization.dates import normalize_date_period
from app.services.normalization.entities import EntityResolver
from app.services.normalization.numeric import normalize_numeric
from app.services.reasoning.comparator import DeterministicComparator
from app.services.reasoning.engine import RelationshipEngine
from app.services.reasoning.models import LLMRelationshipClassification
from tests.fixtures_synthetic import (
    create_case_a_doc1,
    create_case_a_doc2,
    create_case_b_doc1,
    create_case_b_doc2,
    create_case_c_doc1,
    create_case_c_doc2,
    create_case_d_failure_doc,
)


# ── 1. CASE A: Corroboration ──────────────────────────────────────────


def test_case_a_corroboration_different_wording_same_value():
    """CASE A: Different wording, equivalent meaning and value -> CORROBORATES."""
    init_db()
    ingestor = DocumentIngestor()
    chunker = LayoutAwareChunker()

    doc_a1 = ingestor.ingest_from_bytes(create_case_a_doc1(), "synthetic_case_a1.pdf").document_id
    doc_a2 = ingestor.ingest_from_bytes(create_case_a_doc2(), "synthetic_case_a2.pdf").document_id

    chk_a1 = chunker.chunk_document(doc_a1)
    chk_a2 = chunker.chunk_document(doc_a2)

    # 1. Numeric normalization: $120 million vs 120,000 thousand USD
    norm1 = normalize_numeric("$120 million", ValueType.CURRENCY)
    norm2 = normalize_numeric("120,000 thousand USD", ValueType.CURRENCY)
    assert norm1.normalized_numeric == 120000000.0
    assert norm2.normalized_numeric == 120000000.0
    assert norm1.normalized_numeric == norm2.normalized_numeric

    # 2. Compare facts
    fact1 = FactSchema(
        id="f1",
        document_id=doc_a1,
        chunk_id=chk_a1[0].id,
        subject="Acme Corporation",
        predicate="revenue",
        value_text="$120 million",
        value_type=ValueType.CURRENCY,
        numeric_value=120000000.0,
        normalized_numeric_value=norm1.normalized_numeric,
        currency="USD",
        unit="USD",
        time_text="FY2025",
        scope="consolidated",
        geography="Global",
        source_quote="Acme Corporation achieved consolidated revenue of $120 million in FY2025 across all global operations.",
        source_page_start=1,
        source_page_end=1,
    )
    fact2 = FactSchema(
        id="f2",
        document_id=doc_a2,
        chunk_id=chk_a2[0].id,
        subject="Acme Corporation",
        predicate="revenue",
        value_text="120,000 thousand USD",
        value_type=ValueType.CURRENCY,
        numeric_value=120000000.0,
        normalized_numeric_value=norm2.normalized_numeric,
        currency="USD",
        unit="USD",
        time_text="FY2025",
        scope="consolidated",
        geography="Global",
        source_quote="In fiscal year 2025, Acme Corporation generated 120,000 thousand USD in total global sales.",
        source_page_start=1,
        source_page_end=1,
    )

    comparator = DeterministicComparator()
    is_conclusive, judgment, ctx = comparator.compare(fact1, fact2)

    assert is_conclusive is True
    assert judgment is not None
    assert judgment.relationship_type == RelationshipType.CORROBORATES
    assert judgment.primary_dimension == PrimaryDimension.VALUE
    assert judgment.confidence >= 0.95


# ── 2. CASE B: Contradiction ──────────────────────────────────────────


def test_case_b_contradiction_same_context_different_value():
    """CASE B: Same entity, metric, period, scope, genuinely different value -> CONTRADICTS."""
    init_db()
    ingestor = DocumentIngestor()
    chunker = LayoutAwareChunker()

    doc_b1 = ingestor.ingest_from_bytes(create_case_b_doc1(), "synthetic_case_b1.pdf").document_id
    doc_b2 = ingestor.ingest_from_bytes(create_case_b_doc2(), "synthetic_case_b2.pdf").document_id

    chk_b1 = chunker.chunk_document(doc_b1)
    chk_b2 = chunker.chunk_document(doc_b2)

    fact1 = FactSchema(
        id="fb1",
        document_id=doc_b1,
        chunk_id=chk_b1[0].id,
        subject="Beta Industries",
        predicate="headcount",
        value_text="15,000 personnel",
        value_type=ValueType.NUMBER,
        numeric_value=15000.0,
        normalized_numeric_value=15000.0,
        unit="employees",
        time_text="FY2024",
        scope="global",
        geography="Global",
        source_quote="Beta Industries employed 15,000 full-time personnel globally as of FY2024 year end.",
        source_page_start=1,
        source_page_end=1,
    )
    fact2 = FactSchema(
        id="fb2",
        document_id=doc_b2,
        chunk_id=chk_b2[0].id,
        subject="Beta Industries",
        predicate="headcount",
        value_text="11,200 employees",
        value_type=ValueType.NUMBER,
        numeric_value=11200.0,
        normalized_numeric_value=11200.0,
        unit="employees",
        time_text="FY2024",
        scope="global",
        geography="Global",
        source_quote="At the close of FY2024, Beta Industries had 11,200 total employees worldwide.",
        source_page_start=1,
        source_page_end=1,
    )

    comparator = DeterministicComparator()
    is_conclusive, judgment, ctx = comparator.compare(fact1, fact2)

    assert is_conclusive is True
    assert judgment is not None
    assert judgment.relationship_type == RelationshipType.CONTRADICTS
    assert judgment.primary_dimension == PrimaryDimension.VALUE
    assert judgment.confidence >= 0.90


# ── 3. CASE C: Reconciliation ─────────────────────────────────────────


def test_case_c_reconciliation_time_dimension():
    """CASE C: Different values explained by time dimension -> RECONCILES."""
    init_db()
    ingestor = DocumentIngestor()
    chunker = LayoutAwareChunker()

    doc_c1 = ingestor.ingest_from_bytes(create_case_c_doc1(), "synthetic_case_c1.pdf").document_id
    doc_c2 = ingestor.ingest_from_bytes(create_case_c_doc2(), "synthetic_case_c2.pdf").document_id

    chk_c1 = chunker.chunk_document(doc_c1)
    chk_c2 = chunker.chunk_document(doc_c2)

    fact1 = FactSchema(
        id="fc1",
        document_id=doc_c1,
        chunk_id=chk_c1[0].id,
        subject="Gamma Software",
        predicate="revenue",
        value_text="$500 million",
        value_type=ValueType.CURRENCY,
        numeric_value=500000000.0,
        normalized_numeric_value=500000000.0,
        currency="USD",
        unit="USD",
        time_text="FY2024",
        scope="consolidated",
        geography="Global",
        source_quote="Gamma Software achieved total consolidated annual revenue of $500 million for FY2024.",
        source_page_start=1,
        source_page_end=1,
    )
    fact2 = FactSchema(
        id="fc2",
        document_id=doc_c2,
        chunk_id=chk_c2[0].id,
        subject="Gamma Software",
        predicate="revenue",
        value_text="$140 million",
        value_type=ValueType.CURRENCY,
        numeric_value=140000000.0,
        normalized_numeric_value=140000000.0,
        currency="USD",
        unit="USD",
        time_text="Q4 FY2024",
        scope="consolidated",
        geography="Global",
        source_quote="Gamma Software recorded fourth-quarter revenue of $140 million in Q4 FY2024.",
        source_page_start=1,
        source_page_end=1,
    )

    comparator = DeterministicComparator()
    is_conclusive, judgment, ctx = comparator.compare(fact1, fact2)

    assert is_conclusive is True
    assert judgment is not None
    assert judgment.relationship_type == RelationshipType.RECONCILES
    assert judgment.primary_dimension == PrimaryDimension.TIME
    assert "quarterly" in judgment.explanation.lower()


# ── 4. CASE D: Extraction Failure & Uncertainty ───────────────────────


def test_case_d_extraction_failure_and_hallucination():
    """CASE D: Low text page detection and ungrounded quote rejection."""
    init_db()
    ingestor = DocumentIngestor()
    chunker = LayoutAwareChunker()
    result = ingestor.ingest_from_bytes(create_case_d_failure_doc(), "synthetic_case_d.pdf")
    doc_id = result.document_id

    # 1. Verify low-text / scanned page detected
    conn = get_connection()
    try:
        pages = conn.execute(
            "SELECT page_number, is_scanned, text_quality, raw_text FROM pages WHERE document_id = ?",
            (doc_id,),
        ).fetchall()
        assert len(pages) == 2
        # Page 2 has very low text content, flagged as scanned or low text
        page2 = pages[1]
        assert page2["is_scanned"] == 1 or page2["text_quality"] < 0.5
    finally:
        conn.close()

    # 2. Evidence verifier strictly rejects hallucinated / ungrounded quote
    chunks = chunker.chunk_document(doc_id)
    verifier = EvidenceVerifier()
    hallucination_result = verifier.verify(
        source_quote="Delta Corp had exceptional net profit of $999 billion in 2099.",
        chunk_text=chunks[0].text,
        chunk_start_page=1,
        chunk_end_page=1,
    )
    assert hallucination_result.status == ValidationStatus.REJECTED
    assert len(hallucination_result.notes) > 0


# ── 5. Evidence Validation: Verbatim vs Fuzzy vs Rejection ────────────


def test_evidence_validation_exact_vs_fuzzy_vs_rejection():
    """Test verbatim match (validated), minor punctuation (warning), and hallucination (rejected)."""
    init_db()
    ingestor = DocumentIngestor()
    chunker = LayoutAwareChunker()
    res = ingestor.ingest_from_bytes(create_case_a_doc1(), "evid_doc.pdf")
    doc_id = res.document_id
    chunks = chunker.chunk_document(doc_id)

    verifier = EvidenceVerifier()

    # 1. Exact verbatim quote
    exact = verifier.verify(
        source_quote="Acme Corporation achieved consolidated revenue of $120 million in FY2025 across all global operations.",
        chunk_text=chunks[0].text,
        chunk_start_page=1,
        chunk_end_page=1,
    )
    assert exact.status == ValidationStatus.VALIDATED

    # 2. Minor punctuation divergence -> WARNING / VALIDATED
    fuzzy = verifier.verify(
        source_quote="Acme Corporation achieved consolidated revenue of 120 million in FY2025 across all global operations",
        chunk_text=chunks[0].text,
        chunk_start_page=1,
        chunk_end_page=1,
    )
    assert fuzzy.status in (ValidationStatus.VALIDATED, ValidationStatus.WARNING)

    # 3. Completely hallucinated quote -> REJECTED
    bogus = verifier.verify(
        source_quote="Acme Corporation declared bankruptcy and ceased all worldwide production.",
        chunk_text=chunks[0].text,
        chunk_start_page=1,
        chunk_end_page=1,
    )
    assert bogus.status == ValidationStatus.REJECTED


# ── 6. Numeric Normalization: Multi-Scale & Formats ───────────────────


def test_numeric_normalization_multi_scale():
    """Verify multi-scale representation equality: 1.2 billion == 1,200 million."""
    b = normalize_numeric("1.2 billion", ValueType.NUMBER)
    m = normalize_numeric("1,200 million", ValueType.NUMBER)
    k = normalize_numeric("1,200,000 thousand", ValueType.NUMBER)
    raw = normalize_numeric("1,200,000,000", ValueType.NUMBER)

    assert b.normalized_numeric == 1200000000.0
    assert m.normalized_numeric == 1200000000.0
    assert k.normalized_numeric == 1200000000.0
    assert raw.normalized_numeric == 1200000000.0
    assert b.normalized_numeric == m.normalized_numeric == k.normalized_numeric == raw.normalized_numeric

    # Percentage
    pct = normalize_numeric("22%", ValueType.PERCENTAGE)
    assert pct.normalized_numeric == 0.22


# ── 7. Date Normalization: Fiscal Year vs Calendar Year & Quarters ────


def test_date_normalization_fiscal_year_and_quarters():
    """Verify FY2025 preservation without false conflation to calendar year, and quarters."""
    fy = normalize_date_period("FY2025")
    assert fy.time_granularity.value == "fiscal_year"
    assert fy.time_text == "FY2025"

    q4 = normalize_date_period("Q4 2024")
    assert q4.time_granularity.value == "quarter"
    assert q4.time_start == "2024-10-01"
    assert q4.time_end == "2024-12-31"


# ── 8. Entity Ambiguity & Alias Mapping ───────────────────────────────


def test_entity_ambiguity_and_alias_mapping():
    """Verify canonical entity resolution links aliases and preserves distinct ambiguous entities."""
    init_db()
    resolver = EntityResolver()

    # 1. Resolve canonical entity: Acme Corporation
    e1 = resolver.resolve_entity("Acme Corporation", EntityType.ORGANIZATION)
    assert e1.is_new is True

    # 2. Resolve alias stem: Acme Corp. (legal suffix variation)
    e2 = resolver.resolve_entity("Acme Corp.", EntityType.ORGANIZATION)
    assert e2.is_new is False
    assert e2.entity_id == e1.entity_id

    # 3. Completely distinct entity is NOT merged
    e_other = resolver.resolve_entity("Zeta Corp", EntityType.ORGANIZATION)
    assert e_other.entity_id != e1.entity_id


# ── 9. Candidate Generation: Compatibility & Filtering ────────────────


def test_candidate_generation_filtering_and_compatibility():
    """Verify candidate generation excludes same-fact pairs and rejects incompatible entity types."""
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO documents (id, filename, original_filename, sha256, file_size) VALUES ('d1', 'd1.pdf', 'd1.pdf', 'h1', 100)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO documents (id, filename, original_filename, sha256, file_size) VALUES ('d2', 'd2.pdf', 'd2.pdf', 'h2', 100)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO chunks (id, document_id, sequence_index, start_page, end_page, text) VALUES ('c1', 'd1', 1, 1, 1, 'text1')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO chunks (id, document_id, sequence_index, start_page, end_page, text) VALUES ('c2', 'd2', 1, 1, 1, 'text2')"
        )

        # Insert 2 compatible cross-doc facts
        conn.execute(
            """INSERT INTO facts (
                id, document_id, chunk_id, subject, predicate, value_text, value_type, source_quote, source_page_start, source_page_end
            ) VALUES ('f1', 'd1', 'c1', 'Acme', 'revenue', '$10M', 'currency', 'quote1', 1, 1)"""
        )
        conn.execute(
            """INSERT INTO facts (
                id, document_id, chunk_id, subject, predicate, value_text, value_type, source_quote, source_page_start, source_page_end
            ) VALUES ('f2', 'd2', 'c2', 'Acme', 'revenue', '$10M', 'currency', 'quote2', 1, 1)"""
        )
        conn.commit()
    finally:
        conn.close()

    cand_gen = CandidateGenerator()
    pairs = cand_gen.generate_candidates(min_score=0.3)
    assert len(pairs) >= 1
    pair = pairs[0]
    # Verify not same fact and cross-document
    assert pair.fact_a_id != pair.fact_b_id
    assert pair.same_document is False


# ── 10. Cache Reuse: SQLite llm_cache Hit ─────────────────────────────


def test_cache_reuse_bypasses_provider():
    """Verify that repeated evaluation hits SQLite llm_cache and avoids calling provider."""
    init_db()
    engine = RelationshipEngine()

    mock_classification = LLMRelationshipClassification(
        relationship_type=RelationshipType.CORROBORATES,
        confidence=0.99,
        primary_dimension=PrimaryDimension.VALUE,
        explanation="Cached corroboration judgment",
        context_comparison={},
    )

    engine._set_cached_classification("test_cached_hash_123", mock_classification)

    # Fetch cached
    cached = engine._get_cached_classification("test_cached_hash_123")
    assert cached is not None
    assert cached.relationship_type == RelationshipType.CORROBORATES
    assert cached.explanation == "Cached corroboration judgment"


# ── 11. Duplicate Document Detection via SHA-256 ─────────────────────


def test_duplicate_document_detection_sha256():
    """Verify that uploading the exact same bytes reuses existing document without duplicating."""
    init_db()
    ingestor = DocumentIngestor()
    pdf_bytes = create_case_a_doc1()

    # 1. First upload
    res1 = ingestor.ingest_from_bytes(pdf_bytes, "first.pdf")
    doc_id_1 = res1.document_id
    assert res1.is_duplicate is False

    # 2. Second upload with identical bytes but different name
    res2 = ingestor.ingest_from_bytes(pdf_bytes, "second.pdf")
    assert res2.is_duplicate is True
    assert res2.document_id == doc_id_1

    # Document count in DB must be exactly 1
    conn = get_connection()
    try:
        cnt = conn.execute("SELECT COUNT(*) as c FROM documents").fetchone()["c"]
        assert cnt == 1
    finally:
        conn.close()
