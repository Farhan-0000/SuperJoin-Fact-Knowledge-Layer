"""Test suite for Phase 7 — Embeddings and Candidate Generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.database import get_connection, init_db
from app.main import create_app
from app.models.schemas import (
    CandidateStatus,
    EntitySchema,
    EntityType,
    FactSchema,
    TimeGranularity,
    ValueType,
)
from app.services.matching.candidates import (
    CandidateGenerator,
    check_entity_compatibility_and_similarity,
    check_predicate_similarity,
    check_temporal_compatibility,
    check_unit_compatibility,
)
from app.services.matching.embeddings import (
    EmbeddingService,
    MockEmbeddingProvider,
    build_canonical_representation,
    cosine_similarity,
    deserialize_vector,
    serialize_vector,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point database to isolated temporary sqlite file for each test."""
    db_file = tmp_path / "test_facts.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setattr(get_settings(), "database_url", db_url)
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    init_db(str(db_file))
    yield db_file


# ── 1. Canonical Representation Tests ────────────────────────────────


def test_canonical_representation_format():
    """Verify that the canonical string contains all required fields separated cleanly."""
    fact = FactSchema(
        id="fact-1",
        document_id="doc-1",
        chunk_id="chunk-1",
        subject="Apple Inc.",
        predicate="revenue",
        value_text="$383 billion",
        value_type=ValueType.CURRENCY,
        numeric_value=383.0,
        normalized_numeric_value=383_000_000_000.0,
        unit="billion",
        normalized_unit="USD",
        currency="USD",
        time_text="FY 2023",
        time_start="2022-10-01",
        time_end="2023-09-30",
        time_granularity=TimeGranularity.YEAR,
        scope="consolidated",
        geography="global",
        qualifiers_json=json.dumps(["audited", "10-K"]),
        source_quote="Total net sales were $383 billion for fiscal 2023.",
        source_page_start=1,
        source_page_end=1,
    )

    canonical = build_canonical_representation(fact, canonical_entity_name="Apple")
    # Format: canonical subject/entity; predicate; value type; relevant temporal context; scope; geography; qualifiers
    parts = [p.strip() for p in canonical.split(";")]
    assert len(parts) == 7
    assert parts[0] == "Apple"
    assert parts[1] == "revenue"
    assert parts[2] == "currency"
    assert "FY 2023" in parts[3]
    assert parts[4] == "consolidated"
    assert parts[5] == "global"
    assert "audited, 10-K" in parts[6]


# ── 2. Vector Serialization & Cosine Similarity Tests ─────────────────


def test_vector_serialization_and_deserialization():
    """Verify IEEE-754 float32 roundtrip serialization."""
    vec = [0.123456, -0.987654, 0.0, 1.414213, 3.141592]
    blob = serialize_vector(vec)
    assert isinstance(blob, bytes)
    assert len(blob) == len(vec) * 4  # 4 bytes per float32

    recovered = deserialize_vector(blob)
    assert len(recovered) == len(vec)
    for orig, rec in zip(vec, recovered):
        assert rec == pytest.approx(orig, rel=1e-5)


def test_cosine_similarity_edge_cases():
    """Verify cosine similarity properties."""
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert cosine_similarity(v1, v2) == pytest.approx(1.0)

    # Orthogonal
    v3 = [0.0, 1.0, 0.0]
    assert cosine_similarity(v1, v3) == pytest.approx(0.0)

    # Opposing
    v4 = [-1.0, 0.0, 0.0]
    assert cosine_similarity(v1, v4) == pytest.approx(-1.0)

    # Empty or mismatched
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


# ── 3. Mock Provider & SQLite Vector Storage Tests ────────────────────


def test_mock_embedding_provider_properties():
    """Verify MockEmbeddingProvider generates normalized vectors and sensible similarities."""
    provider = MockEmbeddingProvider(dimensions=128)
    texts = [
        "Apple Inc.; revenue; currency; FY 2023; consolidated; global; audited",
        "Apple Inc.; sales; currency; fiscal 2023; consolidated; global; audited",
        "Tesla Motors; battery_capacity; quantity; 2024; automotive; usa; none",
    ]
    embs = provider.get_embeddings(texts)
    assert len(embs) == 3
    assert len(embs[0]) == 128

    sim_related = cosine_similarity(embs[0], embs[1])
    sim_unrelated = cosine_similarity(embs[0], embs[2])

    # Related business claims should have noticeably higher similarity than disjoint claim
    assert sim_related > sim_unrelated
    assert sim_related > 0.60


def test_embedding_service_sqlite_persistence(tmp_path: Path):
    """Verify embeddings are stored in SQLite as binary vectors and re-used via hash."""
    db_file = str(tmp_path / "test_facts.db")
    conn = get_connection(db_file)
    conn.execute(
        "INSERT INTO documents (id, filename, original_filename, sha256, file_size) VALUES ('doc-1', 'test.pdf', 'test.pdf', 'h1', 100)"
    )
    conn.execute(
        "INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text) VALUES ('chunk-1', 'doc-1', 0, 1, 1, 'text')"
    )
    conn.execute(
        """INSERT INTO facts (id, document_id, chunk_id, subject, predicate, value_text, source_quote, source_page_start, source_page_end)
           VALUES ('fact-100', 'doc-1', 'chunk-1', 'Microsoft', 'revenue', '$211B', 'quote', 1, 1)"""
    )
    conn.commit()
    conn.close()

    provider = MockEmbeddingProvider(dimensions=64)
    service = EmbeddingService(provider=provider, db_path=db_file)

    fact = FactSchema(
        id="fact-100",
        document_id="doc-1",
        chunk_id="chunk-1",
        subject="Microsoft",
        predicate="revenue",
        value_text="$211 billion",
        value_type=ValueType.CURRENCY,
        time_text="2023",
        source_quote="Revenue was $211 billion in 2023.",
        source_page_start=1,
        source_page_end=1,
    )

    # 1. Embed and persist
    res = service.embed_facts([fact])
    assert len(res) == 1
    assert res[0].fact_id == "fact-100"
    assert res[0].dimensions == 64
    assert res[0].vector_blob is not None

    # 2. Verify stored in SQLite
    conn = get_connection(db_file)
    row = conn.execute(
        "SELECT * FROM fact_embeddings WHERE fact_id = ?", ("fact-100",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["dimensions"] == 64
    assert len(row["vector_blob"]) == 64 * 4

    # 3. Retrieve via get_fact_embedding
    vec = service.get_fact_embedding("fact-100")
    assert vec is not None
    assert len(vec) == 64

    # 4. Re-embedding without changes should hit cache (no duplicate insert error)
    res2 = service.embed_facts([fact])
    assert len(res2) == 1
    assert res2[0].id == res[0].id


# ── 4. Candidate Compatibility Checks Tests ───────────────────────────


def test_reject_incompatible_entity_types():
    """Clearly incompatible entity types (e.g. PERSON vs ORGANIZATION) must be rejected."""
    entity_org = EntitySchema(
        id="ent-apple", canonical_name="Apple Inc.", entity_type=EntityType.ORGANIZATION
    )
    entity_person = EntitySchema(
        id="ent-tim", canonical_name="Tim Cook", entity_type=EntityType.PERSON
    )

    fact_org = FactSchema(
        id="f-org",
        document_id="doc-1",
        chunk_id="c-1",
        subject="Apple Inc.",
        entity_id="ent-apple",
        predicate="revenue",
        value_text="$383 billion",
        source_quote="Apple revenue",
        source_page_start=1,
        source_page_end=1,
    )
    fact_person = FactSchema(
        id="f-per",
        document_id="doc-1",
        chunk_id="c-1",
        subject="Tim Cook",
        entity_id="ent-tim",
        predicate="chief_executive_officer",
        value_text="CEO",
        source_quote="Tim Cook CEO",
        source_page_start=1,
        source_page_end=1,
    )

    compat, sim, reasons = check_entity_compatibility_and_similarity(
        fact_org, fact_person, entity_org, entity_person
    )
    assert compat is False
    assert sim == 0.0
    assert any("incompatible entity types" in r for r in reasons)


def test_reject_incompatible_units():
    """Incompatible units such as percentage vs currency must be rejected."""
    fact_pct = FactSchema(
        id="f-1",
        document_id="doc-1",
        chunk_id="c-1",
        subject="Alphabet",
        predicate="operating_margin",
        value_text="25%",
        value_type=ValueType.PERCENTAGE,
        unit="%",
        source_quote="Margin was 25%",
        source_page_start=1,
        source_page_end=1,
    )
    fact_usd = FactSchema(
        id="f-2",
        document_id="doc-2",
        chunk_id="c-2",
        subject="Alphabet",
        predicate="revenue",
        value_text="$307 billion",
        value_type=ValueType.CURRENCY,
        currency="USD",
        source_quote="Revenue was $307 billion",
        source_page_start=1,
        source_page_end=1,
    )

    compat, reasons = check_unit_compatibility(fact_pct, fact_usd)
    assert compat is False
    assert any("percentage vs monetary" in r for r in reasons)


def test_temporal_compatibility_same_fiscal_year():
    """Identical fiscal years or spans must be detected as compatible."""
    f1 = FactSchema(
        id="f-1",
        document_id="doc-1",
        chunk_id="c-1",
        subject="Apple",
        predicate="revenue",
        value_text="$383B",
        time_text="FY2023",
        source_quote="q",
        source_page_start=1,
        source_page_end=1,
    )
    f2 = FactSchema(
        id="f-2",
        document_id="doc-2",
        chunk_id="c-2",
        subject="Apple",
        predicate="sales",
        value_text="$383,285M",
        time_text="Fiscal Year 2023",
        source_quote="q",
        source_page_start=1,
        source_page_end=1,
    )

    compat, reasons = check_temporal_compatibility(f1, f2)
    assert compat is True
    assert "same fiscal year" in reasons


def test_predicate_similarity_family():
    """Revenue and sales should yield high predicate semantic similarity (0.91)."""
    f1 = FactSchema(
        id="f-1",
        document_id="doc-1",
        chunk_id="c-1",
        subject="Apple",
        predicate="revenue",
        value_text="1",
        source_quote="q",
        source_page_start=1,
        source_page_end=1,
    )
    f2 = FactSchema(
        id="f-2",
        document_id="doc-2",
        chunk_id="c-2",
        subject="Apple",
        predicate="sales",
        value_text="1",
        source_quote="q",
        source_page_start=1,
        source_page_end=1,
    )

    sim, reasons = check_predicate_similarity(f1, f2)
    assert sim == 0.91
    assert "predicate semantic similarity 0.91" in reasons


# ── 5. End-to-End Candidate Generation Pipeline Tests ─────────────────


def test_candidate_generation_pipeline_synthetic_facts(tmp_path: Path):
    """Verify conservative candidate retrieval, scoring, explainable reasons,

    exclusion of self-comparison, canonical ID ordering, and cross-document preference.
    """
    db_file = str(tmp_path / "test_facts.db")
    conn = get_connection(db_file)

    # 1. Populate documents and chunks
    conn.execute(
        """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
           VALUES ('doc-A', 'docA.pdf', 'docA.pdf', 'hashA', 100),
                  ('doc-B', 'docB.pdf', 'docB.pdf', 'hashB', 200),
                  ('doc-C', 'docC.pdf', 'docC.pdf', 'hashC', 300)"""
    )
    conn.execute(
        """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
           VALUES ('c-1', 'doc-A', 0, 1, 1, 'chunk 1 text'),
                  ('c-2', 'doc-B', 0, 2, 2, 'chunk 2 text'),
                  ('c-3', 'doc-C', 0, 5, 5, 'chunk 3 text')"""
    )

    # 2. Populate synthetic entities
    conn.execute(
        """INSERT INTO entities (id, canonical_name, entity_type, confidence)
           VALUES ('ent-apple', 'Apple Inc.', 'organization', 1.0),
                  ('ent-msft', 'Microsoft Corp.', 'organization', 1.0),
                  ('ent-tim', 'Tim Cook', 'person', 1.0)"""
    )

    # 3. Populate synthetic facts
    # Fact 1 (Doc A): Apple revenue FY2023 $383 billion
    # Fact 2 (Doc B): Apple net sales 2023 $383,285 million (cross-doc match for Fact 1)
    # Fact 3 (Doc B): Apple operating margin 2023 29.8% (unit incompatible with Fact 1)
    # Fact 4 (Doc A): Tim Cook CEO 2023 (entity incompatible with Fact 1)
    # Fact 5 (Doc C): Microsoft revenue FY2023 $211 billion (different entity)
    facts = [
        FactSchema(
            id="fact-apple-rev-docA",
            document_id="doc-A",
            chunk_id="c-1",
            subject="Apple Inc.",
            entity_id="ent-apple",
            predicate="revenue",
            value_text="$383 billion",
            value_type=ValueType.CURRENCY,
            currency="USD",
            time_text="FY2023",
            source_quote="Apple revenue was $383 billion for FY2023.",
            source_page_start=1,
            source_page_end=1,
        ),
        FactSchema(
            id="fact-apple-sales-docB",
            document_id="doc-B",
            chunk_id="c-2",
            subject="Apple Inc.",
            entity_id="ent-apple",
            predicate="sales",
            value_text="$383,285 million",
            value_type=ValueType.CURRENCY,
            currency="USD",
            time_text="fiscal 2023",
            source_quote="Total net sales reached $383,285 million in fiscal 2023.",
            source_page_start=2,
            source_page_end=2,
        ),
        FactSchema(
            id="fact-apple-margin-docB",
            document_id="doc-B",
            chunk_id="c-2",
            subject="Apple Inc.",
            entity_id="ent-apple",
            predicate="operating_margin",
            value_text="29.8%",
            value_type=ValueType.PERCENTAGE,
            unit="%",
            time_text="fiscal 2023",
            source_quote="Operating margin was 29.8%.",
            source_page_start=2,
            source_page_end=2,
        ),
        FactSchema(
            id="fact-tim-ceo-docA",
            document_id="doc-A",
            chunk_id="c-1",
            subject="Tim Cook",
            entity_id="ent-tim",
            predicate="chief_executive_officer",
            value_text="CEO",
            value_type=ValueType.TEXT,
            time_text="2023",
            source_quote="Tim Cook served as CEO in 2023.",
            source_page_start=1,
            source_page_end=1,
        ),
        FactSchema(
            id="fact-msft-rev-docC",
            document_id="doc-C",
            chunk_id="c-3",
            subject="Microsoft Corp.",
            entity_id="ent-msft",
            predicate="revenue",
            value_text="$211 billion",
            value_type=ValueType.CURRENCY,
            currency="USD",
            time_text="FY2023",
            source_quote="Microsoft revenue was $211 billion.",
            source_page_start=5,
            source_page_end=5,
        ),
    ]

    for f in facts:
        conn.execute(
            """INSERT INTO facts (
                id, document_id, chunk_id, subject, entity_id, predicate,
                value_text, value_type, currency, unit, time_text,
                source_quote, source_page_start, source_page_end
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f.id,
                f.document_id,
                f.chunk_id,
                f.subject,
                f.entity_id,
                f.predicate,
                f.value_text,
                f.value_type.value,
                f.currency,
                f.unit,
                f.time_text,
                f.source_quote,
                f.source_page_start,
                f.source_page_end,
            ),
        )
    conn.commit()
    conn.close()

    # 4. Run candidate generator
    provider = MockEmbeddingProvider(dimensions=128)
    emb_service = EmbeddingService(provider=provider, db_path=db_file)
    generator = CandidateGenerator(
        embedding_service=emb_service,
        db_path=db_file,
        min_score=0.60,
        top_k=10,
    )

    candidates = generator.generate_candidates()

    # Verify candidates generated
    assert len(candidates) >= 1

    # Check top candidate: Apple revenue (Doc A) <-> Apple sales (Doc B)
    top_pair = next(
        (
            c
            for c in candidates
            if {c.fact_a_id, c.fact_b_id}
            == {"fact-apple-rev-docA", "fact-apple-sales-docB"}
        ),
        None,
    )
    assert top_pair is not None
    assert top_pair.same_document is False  # Cross-document
    assert top_pair.entity_similarity == 1.0
    assert top_pair.predicate_similarity == 0.91
    assert top_pair.period_compatible is True
    assert top_pair.candidate_score >= 0.75

    # Check selection reasons
    reasons = json.loads(top_pair.reason_json)
    assert "same canonical entity" in reasons
    assert "predicate semantic similarity 0.91" in reasons
    assert "same fiscal year" in reasons

    # Rule checks:
    # 1. No self comparison
    for c in candidates:
        assert c.fact_a_id != c.fact_b_id
        # Canonical ordering
        assert c.fact_a_id < c.fact_b_id

    # 2. Incompatible entity types rejected
    for c in candidates:
        pair_ids = {c.fact_a_id, c.fact_b_id}
        assert not ("fact-apple-rev-docA" in pair_ids and "fact-tim-ceo-docA" in pair_ids)

    # 3. Incompatible units rejected
    for c in candidates:
        pair_ids = {c.fact_a_id, c.fact_b_id}
        assert not ("fact-apple-rev-docA" in pair_ids and "fact-apple-margin-docB" in pair_ids)

    # 4. Status is pending (relationship LLM NOT called)
    for c in candidates:
        assert c.status == CandidateStatus.PENDING

    # 5. Check SQLite persistence
    conn = get_connection(db_file)
    rows = conn.execute("SELECT * FROM candidate_pairs").fetchall()
    conn.close()
    assert len(rows) == len(candidates)


# ── 6. API Route Tests ───────────────────────────────────────────────


def test_candidates_api_endpoints(tmp_path: Path):
    """Verify POST /api/candidates/generate and GET /api/candidates."""
    app = create_app()
    client = TestClient(app)

    db_file = str(tmp_path / "test_facts.db")
    conn = get_connection(db_file)
    conn.execute(
        """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
           VALUES ('d-1', 'd1.pdf', 'd1.pdf', 'h1', 100),
                  ('d-2', 'd2.pdf', 'd2.pdf', 'hash2', 200)"""
    )
    conn.execute(
        """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
           VALUES ('c-1', 'd-1', 0, 1, 1, 'text 1'),
                  ('c-2', 'd-2', 0, 2, 2, 'text 2')"""
    )
    conn.execute(
        """INSERT INTO facts (
            id, document_id, chunk_id, subject, predicate,
            value_text, value_type, currency, time_text,
            source_quote, source_page_start, source_page_end
        ) VALUES
        ('f-1', 'd-1', 'c-1', 'Tesla', 'revenue', '$96B', 'currency', 'USD', '2023', 'q1', 1, 1),
        ('f-2', 'd-2', 'c-2', 'Tesla', 'revenue', '$96.7B', 'currency', 'USD', '2023', 'q2', 2, 2)"""
    )
    conn.commit()
    conn.close()

    # 1. Generate candidates via API
    resp = client.post(
        "/api/candidates/generate",
        json={"min_score": 0.50, "top_k": 5},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"
    assert data[0]["same_document"] is False

    # 2. Query list
    resp_list = client.get("/api/candidates")
    assert resp_list.status_code == 200
    list_data = resp_list.json()
    assert len(list_data) == 1

    # 3. Query single candidate
    pair_id = list_data[0]["id"]
    resp_single = client.get(f"/api/candidates/{pair_id}")
    assert resp_single.status_code == 200
    assert resp_single.json()["id"] == pair_id


def test_candidates_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """Verify candidate CLI execution."""
    from app.cli.candidates import main as cli_main

    db_file = str(tmp_path / "test_facts.db")
    conn = get_connection(db_file)
    conn.execute(
        """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
           VALUES ('doc-1', 'd1.pdf', 'd1.pdf', 'h1', 100),
                  ('doc-2', 'd2.pdf', 'd2.pdf', 'h2', 200)"""
    )
    conn.execute(
        """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
           VALUES ('c-1', 'doc-1', 0, 1, 1, 'text 1'),
                  ('c-2', 'doc-2', 0, 2, 2, 'text 2')"""
    )
    conn.execute(
        """INSERT INTO facts (
            id, document_id, chunk_id, subject, predicate,
            value_text, value_type, currency, time_text,
            source_quote, source_page_start, source_page_end
        ) VALUES
        ('f-1', 'doc-1', 'c-1', 'Amazon', 'revenue', '$500B', 'currency', 'USD', '2023', 'q1', 1, 1),
        ('f-2', 'doc-2', 'c-2', 'Amazon', 'revenue', '$514B', 'currency', 'USD', '2023', 'q2', 2, 2)"""
    )
    conn.commit()
    conn.close()

    exit_code = cli_main(["--threshold", "0.50", "--top-k", "5"])
    assert exit_code == 0

    captured = capsys.readouterr().out
    assert "Generated 1 candidate pairs" in captured
    assert "Amazon" in captured or "Score:" in captured

