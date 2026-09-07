"""Test suite for Phase 8 — Hybrid Relationship Engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.database import get_connection, init_db
from app.main import create_app
from app.models.schemas import (
    CandidatePairSchema,
    CandidateStatus,
    EntitySchema,
    EntityType,
    FactSchema,
    PrimaryDimension,
    RelationshipType,
    TimeGranularity,
    ValidationStatus,
    ValueType,
)
from app.services.reasoning.comparator import DeterministicComparator
from app.services.reasoning.engine import RelationshipEngine
from app.services.reasoning.models import LLMRelationshipClassification
from app.services.reasoning.providers import MockRelationshipProvider


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point database to isolated temporary sqlite file for each test."""
    db_file = tmp_path / "test_facts.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setattr(get_settings(), "database_url", db_url)
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    init_db(str(db_file))
    yield db_file


# ── 1. Deterministic Comparison Tests ─────────────────────────────────


def test_deterministic_corroboration():
    """Identical entity, predicate, period, unit, and matching values must corroborate."""
    comparator = DeterministicComparator()
    entity = EntitySchema(id="e-apple", canonical_name="Apple Inc.", entity_type=EntityType.ORGANIZATION)

    fact_a = FactSchema(
        id="f-1",
        document_id="d-1",
        chunk_id="c-1",
        subject="Apple Inc.",
        entity_id="e-apple",
        predicate="revenue",
        value_text="$383 billion",
        value_type=ValueType.CURRENCY,
        numeric_value=383.0,
        normalized_numeric_value=383_000_000_000.0,
        currency="USD",
        time_text="FY2023",
        scope="consolidated",
        geography="global",
        source_quote="Apple FY2023 revenue was $383 billion.",
        source_page_start=1,
        source_page_end=1,
    )
    fact_b = FactSchema(
        id="f-2",
        document_id="d-2",
        chunk_id="c-2",
        subject="Apple Inc.",
        entity_id="e-apple",
        predicate="revenue",
        value_text="$383,000 million",
        value_type=ValueType.CURRENCY,
        numeric_value=383000.0,
        normalized_numeric_value=383_000_000_000.0,
        currency="USD",
        time_text="Fiscal Year 2023",
        scope="consolidated",
        geography="global",
        source_quote="Apple reported $383,000 million in revenue for fiscal year 2023.",
        source_page_start=2,
        source_page_end=2,
    )

    is_conclusive, classification, ctx = comparator.compare(fact_a, fact_b, entity, entity)
    assert is_conclusive is True
    assert classification is not None
    assert classification.relationship_type == RelationshipType.CORROBORATES
    assert classification.confidence == 1.0
    assert classification.primary_dimension == PrimaryDimension.VALUE
    assert "corroborate" in classification.explanation.lower()


def test_deterministic_contradiction_same_context():
    """Different values under identical entity, metric, period, and scope must contradict."""
    comparator = DeterministicComparator()
    entity = EntitySchema(id="e-apple", canonical_name="Apple Inc.", entity_type=EntityType.ORGANIZATION)

    fact_a = FactSchema(
        id="f-1",
        document_id="d-1",
        chunk_id="c-1",
        subject="Apple Inc.",
        entity_id="e-apple",
        predicate="revenue",
        value_text="$383 billion",
        value_type=ValueType.CURRENCY,
        numeric_value=383.0,
        normalized_numeric_value=383_000_000_000.0,
        currency="USD",
        time_text="FY2023",
        scope="consolidated",
        geography="global",
        source_quote="Apple revenue was $383 billion for FY2023.",
        source_page_start=1,
        source_page_end=1,
    )
    fact_b = FactSchema(
        id="f-2",
        document_id="d-2",
        chunk_id="c-2",
        subject="Apple Inc.",
        entity_id="e-apple",
        predicate="revenue",
        value_text="$300 billion",
        value_type=ValueType.CURRENCY,
        numeric_value=300.0,
        normalized_numeric_value=300_000_000_000.0,
        currency="USD",
        time_text="FY2023",
        scope="consolidated",
        geography="global",
        source_quote="Apple revenue was $300 billion for FY2023.",
        source_page_start=2,
        source_page_end=2,
    )

    is_conclusive, classification, ctx = comparator.compare(fact_a, fact_b, entity, entity)
    assert is_conclusive is True
    assert classification is not None
    assert classification.relationship_type == RelationshipType.CONTRADICTS
    assert classification.confidence >= 0.90
    assert classification.primary_dimension == PrimaryDimension.VALUE
    assert "contradiction" in classification.explanation.lower()


def test_different_values_not_contradiction_time_reconciliation():
    """CRITICAL RULE: Different values due to differing time periods (FY vs Q4) must RECONCILE, NOT contradict."""
    comparator = DeterministicComparator()
    entity = EntitySchema(id="e-apple", canonical_name="Apple Inc.", entity_type=EntityType.ORGANIZATION)

    fact_full_year = FactSchema(
        id="f-fy",
        document_id="d-1",
        chunk_id="c-1",
        subject="Apple Inc.",
        entity_id="e-apple",
        predicate="revenue",
        value_text="$383 billion",
        value_type=ValueType.CURRENCY,
        normalized_numeric_value=383_000_000_000.0,
        currency="USD",
        time_text="FY2023",
        scope="consolidated",
        source_quote="Full fiscal year 2023 revenue reached $383 billion.",
        source_page_start=1,
        source_page_end=1,
    )
    fact_quarter = FactSchema(
        id="f-q4",
        document_id="d-2",
        chunk_id="c-2",
        subject="Apple Inc.",
        entity_id="e-apple",
        predicate="revenue",
        value_text="$89 billion",
        value_type=ValueType.CURRENCY,
        normalized_numeric_value=89_000_000_000.0,
        currency="USD",
        time_text="Q4 2023",
        scope="consolidated",
        source_quote="Q4 2023 revenue was $89 billion.",
        source_page_start=5,
        source_page_end=5,
    )

    is_conclusive, classification, ctx = comparator.compare(fact_full_year, fact_quarter, entity, entity)
    assert is_conclusive is True
    assert classification is not None
    assert classification.relationship_type == RelationshipType.RECONCILES
    assert classification.relationship_type != RelationshipType.CONTRADICTS
    assert classification.primary_dimension == PrimaryDimension.TIME
    assert "period" in classification.explanation.lower() or "quarter" in classification.explanation.lower()


def test_different_values_not_contradiction_scope_reconciliation():
    """CRITICAL RULE: Different values due to differing scope (consolidated vs segment) must RECONCILE, NOT contradict."""
    comparator = DeterministicComparator()
    entity = EntitySchema(id="e-goog", canonical_name="Alphabet Inc.", entity_type=EntityType.ORGANIZATION)

    fact_consolidated = FactSchema(
        id="f-cons",
        document_id="d-1",
        chunk_id="c-1",
        subject="Alphabet Inc.",
        entity_id="e-goog",
        predicate="revenue",
        value_text="$307 billion",
        value_type=ValueType.CURRENCY,
        normalized_numeric_value=307_000_000_000.0,
        currency="USD",
        time_text="2023",
        scope="consolidated",
        source_quote="Alphabet consolidated revenues were $307 billion.",
        source_page_start=1,
        source_page_end=1,
    )
    fact_segment = FactSchema(
        id="f-seg",
        document_id="d-2",
        chunk_id="c-2",
        subject="Alphabet Inc.",
        entity_id="e-goog",
        predicate="revenue",
        value_text="$33 billion",
        value_type=ValueType.CURRENCY,
        normalized_numeric_value=33_000_000_000.0,
        currency="USD",
        time_text="2023",
        scope="Google Cloud",
        source_quote="Google Cloud revenues were $33 billion.",
        source_page_start=3,
        source_page_end=3,
    )

    is_conclusive, classification, ctx = comparator.compare(fact_consolidated, fact_segment, entity, entity)
    assert is_conclusive is True
    assert classification is not None
    assert classification.relationship_type == RelationshipType.RECONCILES
    assert classification.relationship_type != RelationshipType.CONTRADICTS
    assert classification.primary_dimension == PrimaryDimension.SCOPE


def test_unit_reconciliation_percentage_vs_monetary():
    """Comparing percentage metric against monetary metric reconciles across unit dimension."""
    comparator = DeterministicComparator()
    entity = EntitySchema(id="e-1", canonical_name="Meta", entity_type=EntityType.ORGANIZATION)

    f_pct = FactSchema(
        id="f-pct",
        document_id="d-1",
        chunk_id="c-1",
        subject="Meta",
        entity_id="e-1",
        predicate="operating_margin",
        value_text="35%",
        value_type=ValueType.PERCENTAGE,
        unit="%",
        source_quote="Margin was 35%",
        source_page_start=1,
        source_page_end=1,
    )
    f_num = FactSchema(
        id="f-num",
        document_id="d-2",
        chunk_id="c-2",
        subject="Meta",
        entity_id="e-1",
        predicate="operating_margin",
        value_text="$46 billion",
        value_type=ValueType.CURRENCY,
        currency="USD",
        source_quote="Operating income was $46 billion",
        source_page_start=2,
        source_page_end=2,
    )

    is_conclusive, classification, ctx = comparator.compare(f_pct, f_num, entity, entity)
    assert is_conclusive is True
    assert classification is not None
    assert classification.relationship_type == RelationshipType.RECONCILES
    assert classification.primary_dimension == PrimaryDimension.UNIT


def test_unrelated_facts():
    """Different entities or completely unrelated predicates must be classified UNRELATED."""
    comparator = DeterministicComparator()
    e_apple = EntitySchema(id="e-a", canonical_name="Apple Inc.", entity_type=EntityType.ORGANIZATION)
    e_msft = EntitySchema(id="e-m", canonical_name="Microsoft Corp.", entity_type=EntityType.ORGANIZATION)

    f_a = FactSchema(
        id="f-a",
        document_id="d-1",
        chunk_id="c-1",
        subject="Apple Inc.",
        entity_id="e-a",
        predicate="revenue",
        value_text="$383B",
        source_quote="q",
        source_page_start=1,
        source_page_end=1,
    )
    f_b = FactSchema(
        id="f-b",
        document_id="d-2",
        chunk_id="c-2",
        subject="Microsoft Corp.",
        entity_id="e-m",
        predicate="revenue",
        value_text="$211B",
        source_quote="q",
        source_page_start=1,
        source_page_end=1,
    )

    is_conclusive, classification, ctx = comparator.compare(f_a, f_b, e_apple, e_msft)
    assert is_conclusive is True
    assert classification is not None
    assert classification.relationship_type == RelationshipType.UNRELATED
    assert classification.primary_dimension == PrimaryDimension.ENTITY


# ── 2. Hybrid Engine & LLM Fallback Tests ─────────────────────────────


def test_llm_fallback_semantic_judgment(tmp_path: Path):
    """When predicates are related but distinct (revenue vs sales), engine invokes LLM provider."""
    db_file = str(tmp_path / "test_facts.db")
    provider = MockRelationshipProvider()
    engine = RelationshipEngine(provider=provider, db_path=db_file)

    entity = EntitySchema(id="e-apple", canonical_name="Apple Inc.", entity_type=EntityType.ORGANIZATION)
    fact_rev = FactSchema(
        id="f-rev",
        document_id="d-1",
        chunk_id="c-1",
        subject="Apple Inc.",
        entity_id="e-apple",
        predicate="revenue",
        value_text="$383 billion",
        value_type=ValueType.CURRENCY,
        currency="USD",
        time_text="2023",
        source_quote="Revenue was $383 billion.",
        source_page_start=1,
        source_page_end=1,
    )
    fact_sales = FactSchema(
        id="f-sales",
        document_id="d-2",
        chunk_id="c-2",
        subject="Apple Inc.",
        entity_id="e-apple",
        predicate="sales",
        value_text="$383,285 million",
        value_type=ValueType.CURRENCY,
        currency="USD",
        time_text="2023",
        source_quote="Net sales reached $383,285 million.",
        source_page_start=2,
        source_page_end=2,
    )

    rel = engine.evaluate_pair(fact_rev, fact_sales, entity, entity)
    assert rel.relationship_type == RelationshipType.RECONCILES
    assert rel.primary_dimension == PrimaryDimension.DEFINITION
    assert "revenue" in rel.explanation.lower() and "sales" in rel.explanation.lower()


def test_llm_caching(tmp_path: Path):
    """Second evaluation of the same pair hits SQLite llm_cache and avoids LLM re-computation."""
    db_file = str(tmp_path / "test_facts.db")

    call_count = 0

    class CountingProvider(MockRelationshipProvider):
        def classify(self, messages, model):
            nonlocal call_count
            call_count += 1
            return super().classify(messages, model)

    provider = CountingProvider()
    engine = RelationshipEngine(provider=provider, db_path=db_file)

    entity = EntitySchema(id="e-1", canonical_name="Acme", entity_type=EntityType.ORGANIZATION)
    f1 = FactSchema(
        id="f-1",
        document_id="d-1",
        chunk_id="c-1",
        subject="Acme",
        entity_id="e-1",
        predicate="revenue",
        value_text="$100M",
        time_text="2023",
        source_quote="q1",
        source_page_start=1,
        source_page_end=1,
    )
    f2 = FactSchema(
        id="f-2",
        document_id="d-2",
        chunk_id="c-2",
        subject="Acme",
        entity_id="e-1",
        predicate="sales",
        value_text="$105M",
        time_text="2023",
        source_quote="q2",
        source_page_start=2,
        source_page_end=2,
    )

    # 1. First evaluation: invokes provider
    rel1 = engine.evaluate_pair(f1, f2, entity, entity)
    assert call_count == 1

    # Verify cached in SQLite llm_cache
    conn = get_connection(db_file)
    row = conn.execute("SELECT * FROM llm_cache WHERE operation = 'relationship_reasoning'").fetchone()
    conn.close()
    assert row is not None

    # 2. Second evaluation: must hit cache!
    rel2 = engine.evaluate_pair(f1, f2, entity, entity)
    assert call_count == 1  # No new LLM call!
    assert rel2.relationship_type == rel1.relationship_type


def test_candidate_pair_status_updated_to_evaluated(tmp_path: Path):
    """Evaluating candidate pairs updates candidate_pairs status from 'pending' to 'evaluated'."""
    db_file = str(tmp_path / "test_facts.db")
    conn = get_connection(db_file)

    conn.execute(
        """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
           VALUES ('doc-A', 'a.pdf', 'a.pdf', 'hA', 100),
                  ('doc-B', 'b.pdf', 'b.pdf', 'hB', 200)"""
    )
    conn.execute(
        """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
           VALUES ('c-1', 'doc-A', 0, 1, 1, 'text 1'),
                  ('c-2', 'doc-B', 0, 2, 2, 'text 2')"""
    )
    conn.execute(
        """INSERT INTO entities (id, canonical_name, entity_type, confidence)
           VALUES ('ent-1', 'NVIDIA Corp.', 'organization', 1.0)"""
    )
    conn.execute(
        """INSERT INTO facts (
            id, document_id, chunk_id, subject, entity_id, predicate,
            value_text, value_type, currency, normalized_numeric_value, time_text,
            source_quote, source_page_start, source_page_end
        ) VALUES
        ('f-nvda-1', 'doc-A', 'c-1', 'NVIDIA Corp.', 'ent-1', 'revenue', '$60.9 billion', 'currency', 'USD', 60900000000.0, 'FY2024', 'NVIDIA revenue was $60.9B for FY2024.', 1, 1),
        ('f-nvda-2', 'doc-B', 'c-2', 'NVIDIA Corp.', 'ent-1', 'revenue', '$60,922 million', 'currency', 'USD', 60922000000.0, 'FY2024', 'NVIDIA reported $60,922 million in FY2024 revenue.', 2, 2)"""
    )
    conn.execute(
        """INSERT INTO candidate_pairs (id, fact_a_id, fact_b_id, same_document, candidate_score, status)
           VALUES ('cp-1', 'f-nvda-1', 'f-nvda-2', 0, 0.95, 'pending')"""
    )
    conn.commit()
    conn.close()

    engine = RelationshipEngine(db_path=db_file)
    results = engine.evaluate_candidates()
    assert len(results) == 1
    rel = results[0]
    assert rel.relationship_type == RelationshipType.CORROBORATES
    assert rel.evidence_fact_a == "NVIDIA revenue was $60.9B for FY2024."
    assert rel.evidence_fact_b == "NVIDIA reported $60,922 million in FY2024 revenue."

    # Verify candidate_pairs status updated to 'evaluated'
    conn = get_connection(db_file)
    cp_row = conn.execute("SELECT status FROM candidate_pairs WHERE id = 'cp-1'").fetchone()
    rel_row = conn.execute("SELECT * FROM relationships WHERE id = ?", (rel.id,)).fetchone()
    conn.close()

    assert cp_row["status"] == CandidateStatus.EVALUATED.value
    assert rel_row is not None
    assert rel_row["relationship_type"] == "corroborates"


# ── 3. API & CLI Integration Tests ────────────────────────────────────


def test_relationships_api_endpoints(tmp_path: Path):
    """Verify POST /api/relationships/evaluate and GET /api/relationships."""
    app = create_app()
    client = TestClient(app)

    db_file = str(tmp_path / "test_facts.db")
    conn = get_connection(db_file)
    conn.execute(
        """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
           VALUES ('d-1', 'd1.pdf', 'd1.pdf', 'h1', 100),
                  ('d-2', 'd2.pdf', 'd2.pdf', 'h2', 200)"""
    )
    conn.execute(
        """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
           VALUES ('c-1', 'd-1', 0, 1, 1, 'text 1'),
                  ('c-2', 'd-2', 0, 2, 2, 'text 2')"""
    )
    conn.execute(
        """INSERT INTO facts (
            id, document_id, chunk_id, subject, predicate,
            value_text, value_type, currency, normalized_numeric_value, time_text,
            source_quote, source_page_start, source_page_end
        ) VALUES
        ('f-1', 'd-1', 'c-1', 'Tesla', 'revenue', '$96B', 'currency', 'USD', 96000000000.0, '2023', 'Tesla revenue was $96B in 2023.', 1, 1),
        ('f-2', 'd-2', 'c-2', 'Tesla', 'revenue', '$80B', 'currency', 'USD', 80000000000.0, '2023', 'Tesla revenue was $80B in 2023.', 2, 2)"""
    )
    conn.execute(
        """INSERT INTO candidate_pairs (id, fact_a_id, fact_b_id, status)
           VALUES ('cp-api-1', 'f-1', 'f-2', 'pending')"""
    )
    conn.commit()
    conn.close()

    # 1. Evaluate via API
    resp_eval = client.post("/api/relationships/evaluate", json={"force": False})
    assert resp_eval.status_code == 201
    eval_data = resp_eval.json()
    assert len(eval_data) == 1
    assert eval_data[0]["relationship_type"] == "contradicts"

    # 2. List relationships
    resp_list = client.get("/api/relationships?relationship_type=contradicts")
    assert resp_list.status_code == 200
    list_data = resp_list.json()
    assert len(list_data) == 1

    # 3. Get single relationship
    rel_id = list_data[0]["id"]
    resp_single = client.get(f"/api/relationships/{rel_id}")
    assert resp_single.status_code == 200
    assert resp_single.json()["id"] == rel_id


def test_reconcile_cli(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Verify python -m app.cli.reconcile execution."""
    from app.cli.reconcile import main as cli_main

    db_file = str(tmp_path / "test_facts.db")
    conn = get_connection(db_file)
    conn.execute(
        """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
           VALUES ('d-1', 'd1.pdf', 'd1.pdf', 'h1', 100),
                  ('d-2', 'd2.pdf', 'd2.pdf', 'h2', 200)"""
    )
    conn.execute(
        """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
           VALUES ('c-1', 'd-1', 0, 1, 1, 'text 1'),
                  ('c-2', 'd-2', 0, 2, 2, 'text 2')"""
    )
    conn.execute(
        """INSERT INTO facts (
            id, document_id, chunk_id, subject, predicate,
            value_text, value_type, currency, normalized_numeric_value, time_text,
            source_quote, source_page_start, source_page_end
        ) VALUES
        ('f-1', 'd-1', 'c-1', 'Microsoft', 'revenue', '$211B', 'currency', 'USD', 211000000000.0, '2023', 'q1', 1, 1),
        ('f-2', 'd-2', 'c-2', 'Microsoft', 'revenue', '$211B', 'currency', 'USD', 211000000000.0, '2023', 'q2', 2, 2)"""
    )
    conn.execute(
        """INSERT INTO candidate_pairs (id, fact_a_id, fact_b_id, status)
           VALUES ('cp-cli-1', 'f-1', 'f-2', 'pending')"""
    )
    conn.commit()
    conn.close()

    exit_code = cli_main([])
    assert exit_code == 0

    captured = capsys.readouterr().out
    assert "CORROBORATES" in captured
    assert "Evaluated 1 relationships" in captured
