"""Tests for database initialization and schema integrity."""

from __future__ import annotations

import json
import sqlite3
import uuid

from app.db.database import init_db, get_connection, ALL_TABLES


def _uid() -> str:
    return str(uuid.uuid4())


# ── Schema creation ────────────────────────────────────────────────


def test_init_db_creates_all_tables():
    """init_db should create all 12 expected tables."""
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cursor.fetchall()}
    finally:
        conn.close()

    assert ALL_TABLES.issubset(tables), f"Missing tables: {ALL_TABLES - tables}"


def test_init_db_idempotent():
    """Calling init_db twice should not raise."""
    init_db()
    init_db()


def test_connection_has_wal_and_fk():
    """Connections should enable WAL journal mode and foreign keys."""
    init_db()
    conn = get_connection()
    try:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        conn.close()

    assert journal == "wal"
    assert fk == 1


# ── Document round trip ───────────────────────────────────────────


def test_document_insert_and_read():
    """Insert a document and read it back."""
    init_db()
    conn = get_connection()
    doc_id = _uid()
    try:
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (doc_id, "test.pdf", "original_test.pdf", "abc123hash", 1024, "uploaded"),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        assert row["filename"] == "test.pdf"
        assert row["original_filename"] == "original_test.pdf"
        assert row["sha256"] == "abc123hash"
        assert row["file_size"] == 1024
        assert row["status"] == "uploaded"
    finally:
        conn.close()


def test_document_sha256_unique():
    """Duplicate sha256 should be rejected."""
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (_uid(), "a.pdf", "a.pdf", "same_hash", 100),
        )
        conn.commit()

        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
                   VALUES (?, ?, ?, ?, ?)""",
                (_uid(), "b.pdf", "b.pdf", "same_hash", 200),
            )
    finally:
        conn.close()


# ── Page round trip ────────────────────────────────────────────────


def test_page_insert_and_fk():
    """Insert a page linked to a document."""
    init_db()
    conn = get_connection()
    doc_id = _uid()
    page_id = _uid()
    try:
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, "doc.pdf", "doc.pdf", _uid(), 500),
        )
        conn.execute(
            """INSERT INTO pages (id, document_id, page_number, raw_text)
               VALUES (?, ?, ?, ?)""",
            (page_id, doc_id, 1, "Page one text."),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM pages WHERE id = ?", (page_id,)).fetchone()
        assert row["document_id"] == doc_id
        assert row["page_number"] == 1
        assert row["raw_text"] == "Page one text."
    finally:
        conn.close()


def test_page_unique_per_document_and_number():
    """Same (document_id, page_number) should be rejected."""
    init_db()
    conn = get_connection()
    doc_id = _uid()
    try:
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, "doc.pdf", "doc.pdf", _uid(), 500),
        )
        conn.execute(
            """INSERT INTO pages (id, document_id, page_number, raw_text)
               VALUES (?, ?, ?, ?)""",
            (_uid(), doc_id, 1, "First"),
        )
        conn.commit()

        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO pages (id, document_id, page_number, raw_text)
                   VALUES (?, ?, ?, ?)""",
                (_uid(), doc_id, 1, "Duplicate"),
            )
    finally:
        conn.close()


# ── Block round trip ───────────────────────────────────────────────


def test_block_insert_with_bbox():
    """Insert a block with bounding box coordinates."""
    init_db()
    conn = get_connection()
    doc_id, page_id, block_id = _uid(), _uid(), _uid()
    try:
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, "d.pdf", "d.pdf", _uid(), 100),
        )
        conn.execute(
            """INSERT INTO pages (id, document_id, page_number, raw_text)
               VALUES (?, ?, ?, ?)""",
            (page_id, doc_id, 1, "raw"),
        )
        conn.execute(
            """INSERT INTO blocks (id, page_id, block_index, block_type, text, x0, y0, x1, y1)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (block_id, page_id, 0, "paragraph", "Hello", 10.0, 20.0, 300.0, 50.0),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM blocks WHERE id = ?", (block_id,)).fetchone()
        assert row["block_type"] == "paragraph"
        assert row["x0"] == 10.0
        assert row["y1"] == 50.0
    finally:
        conn.close()


# ── Chunk round trip ───────────────────────────────────────────────


def test_chunk_insert_with_json_fields():
    """Chunks should store block_ids and heading_path as JSON."""
    init_db()
    conn = get_connection()
    doc_id, chunk_id = _uid(), _uid()
    block_ids = json.dumps(["b1", "b2", "b3"])
    heading_path = json.dumps(["Chapter 1", "Section 1.2"])
    try:
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, "d.pdf", "d.pdf", _uid(), 100),
        )
        conn.execute(
            """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page,
                                   block_ids_json, heading_path_json, text, token_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (chunk_id, doc_id, 0, 1, 2, block_ids, heading_path, "chunk text", 50),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        assert json.loads(row["block_ids_json"]) == ["b1", "b2", "b3"]
        assert json.loads(row["heading_path_json"]) == ["Chapter 1", "Section 1.2"]
        assert row["extraction_status"] == "pending"
    finally:
        conn.close()


# ── Fact round trip ────────────────────────────────────────────────


def test_fact_generic_insert():
    """Facts use generic subject/predicate/value, not domain-specific fields."""
    init_db()
    conn = get_connection()
    doc_id, chunk_id, fact_id = _uid(), _uid(), _uid()
    try:
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, "d.pdf", "d.pdf", _uid(), 100),
        )
        conn.execute(
            """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (chunk_id, doc_id, 0, 1, 1, "Revenue was $8.2 billion."),
        )
        conn.execute(
            """INSERT INTO facts (id, document_id, chunk_id, subject, predicate,
                                  value_text, value_type, numeric_value, normalized_numeric_value,
                                  unit, currency, time_text, time_start, time_end, time_granularity,
                                  source_quote, source_page_start, source_page_end,
                                  extraction_confidence, validation_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fact_id, doc_id, chunk_id,
             "Acme Corp", "revenue",
             "$8.2 billion", "currency", 8.2e9, 8200000000.0,
             "USD", "USD",
             "FY2025", "2024-04-01", "2025-03-31", "fiscal_year",
             "Revenue for fiscal year 2025 was $8.2 billion.", 47, 47,
             0.95, "validated"),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
        assert row["subject"] == "Acme Corp"
        assert row["predicate"] == "revenue"
        assert row["value_type"] == "currency"
        assert row["numeric_value"] == 8.2e9
        assert row["time_granularity"] == "fiscal_year"
        assert row["validation_status"] == "validated"
    finally:
        conn.close()


# ── Entity + Alias round trip ──────────────────────────────────────


def test_entity_and_alias():
    """Entity with aliases."""
    init_db()
    conn = get_connection()
    ent_id, alias_id = _uid(), _uid()
    try:
        conn.execute(
            """INSERT INTO entities (id, canonical_name, entity_type, confidence)
               VALUES (?, ?, ?, ?)""",
            (ent_id, "Acme Corporation", "company", 0.95),
        )
        conn.execute(
            """INSERT INTO entity_aliases (id, entity_id, alias, confidence)
               VALUES (?, ?, ?, ?)""",
            (alias_id, ent_id, "Acme Corp.", 0.9),
        )
        conn.commit()

        aliases = conn.execute(
            "SELECT alias FROM entity_aliases WHERE entity_id = ?", (ent_id,)
        ).fetchall()
        assert len(aliases) == 1
        assert aliases[0]["alias"] == "Acme Corp."
    finally:
        conn.close()


# ── Candidate pair round trip ──────────────────────────────────────


def test_candidate_pair_with_reasons():
    """Candidate pairs store selection reasons as JSON."""
    init_db()
    conn = get_connection()
    doc_id, chunk_id = _uid(), _uid()
    fact_a_id, fact_b_id, pair_id = _uid(), _uid(), _uid()
    reasons = json.dumps(["same canonical entity", "predicate similarity 0.91"])
    try:
        # Setup: doc → chunk → 2 facts
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, "d.pdf", "d.pdf", _uid(), 100),
        )
        conn.execute(
            """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (chunk_id, doc_id, 0, 1, 1, "text"),
        )
        for fid in (fact_a_id, fact_b_id):
            conn.execute(
                """INSERT INTO facts (id, document_id, chunk_id, subject, predicate,
                                      value_text, source_quote, source_page_start, source_page_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fid, doc_id, chunk_id, "X", "metric", "100", "quote", 1, 1),
            )
        conn.execute(
            """INSERT INTO candidate_pairs (id, fact_a_id, fact_b_id, same_document,
                                            entity_similarity, candidate_score, reason_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pair_id, fact_a_id, fact_b_id, 0, 0.95, 0.88, reasons, "pending"),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM candidate_pairs WHERE id = ?", (pair_id,)).fetchone()
        assert json.loads(row["reason_json"]) == ["same canonical entity", "predicate similarity 0.91"]
        assert row["status"] == "pending"
    finally:
        conn.close()


# ── Relationship round trip ────────────────────────────────────────


def test_relationship_with_context():
    """Relationship stores structured context comparison as JSON."""
    init_db()
    conn = get_connection()
    doc_id, chunk_id = _uid(), _uid()
    fact_a_id, fact_b_id, rel_id = _uid(), _uid(), _uid()
    ctx = json.dumps({"period_a": "FY2025", "period_b": "Q4 FY2025", "period_match": False})
    try:
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, "d.pdf", "d.pdf", _uid(), 100),
        )
        conn.execute(
            """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (chunk_id, doc_id, 0, 1, 1, "text"),
        )
        for fid in (fact_a_id, fact_b_id):
            conn.execute(
                """INSERT INTO facts (id, document_id, chunk_id, subject, predicate,
                                      value_text, source_quote, source_page_start, source_page_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fid, doc_id, chunk_id, "Co", "rev", "10", "q", 1, 1),
            )
        conn.execute(
            """INSERT INTO relationships (id, fact_a_id, fact_b_id, relationship_type,
                                          confidence, primary_dimension, context_comparison_json,
                                          explanation, evidence_fact_a, evidence_fact_b,
                                          reasoning_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rel_id, fact_a_id, fact_b_id, "reconciles", 0.94, "time", ctx,
             "Different periods", "quote A", "quote B", "v1"),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
        assert row["relationship_type"] == "reconciles"
        assert row["primary_dimension"] == "time"
        parsed = json.loads(row["context_comparison_json"])
        assert parsed["period_match"] is False
    finally:
        conn.close()


# ── Job round trip ─────────────────────────────────────────────────


def test_job_insert():
    """Job record with document IDs as JSON."""
    init_db()
    conn = get_connection()
    job_id = _uid()
    doc_ids = json.dumps(["doc1", "doc2"])
    try:
        conn.execute(
            """INSERT INTO jobs (id, job_type, document_ids_json, status, current_stage)
               VALUES (?, ?, ?, ?, ?)""",
            (job_id, "full", doc_ids, "queued", "ingestion"),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert row["job_type"] == "full"
        assert json.loads(row["document_ids_json"]) == ["doc1", "doc2"]
    finally:
        conn.close()


# ── LLM cache round trip ──────────────────────────────────────────


def test_llm_cache_unique_constraint():
    """LLM cache entries are unique on (operation, model, prompt_version, input_hash)."""
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO llm_cache (id, operation, model, prompt_version, input_hash, response_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_uid(), "extraction", "gpt-4o", "v1", "hash123", '{"facts": []}'),
        )
        conn.commit()

        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO llm_cache (id, operation, model, prompt_version, input_hash, response_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (_uid(), "extraction", "gpt-4o", "v1", "hash123", '{"facts": []}'),
            )
    finally:
        conn.close()


# ── Foreign key cascade ───────────────────────────────────────────


def test_cascade_delete_document_removes_pages_and_facts():
    """Deleting a document should cascade to pages, chunks, and facts."""
    init_db()
    conn = get_connection()
    doc_id, page_id, chunk_id, fact_id = _uid(), _uid(), _uid(), _uid()
    try:
        conn.execute(
            """INSERT INTO documents (id, filename, original_filename, sha256, file_size)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, "d.pdf", "d.pdf", _uid(), 100),
        )
        conn.execute(
            """INSERT INTO pages (id, document_id, page_number, raw_text)
               VALUES (?, ?, ?, ?)""",
            (page_id, doc_id, 1, "text"),
        )
        conn.execute(
            """INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (chunk_id, doc_id, 0, 1, 1, "chunk text"),
        )
        conn.execute(
            """INSERT INTO facts (id, document_id, chunk_id, subject, predicate,
                                  value_text, source_quote, source_page_start, source_page_end)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fact_id, doc_id, chunk_id, "X", "y", "z", "q", 1, 1),
        )
        conn.commit()

        # Delete document
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()

        assert conn.execute("SELECT COUNT(*) FROM pages WHERE document_id = ?", (doc_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM facts WHERE document_id = ?", (doc_id,)).fetchone()[0] == 0
    finally:
        conn.close()
