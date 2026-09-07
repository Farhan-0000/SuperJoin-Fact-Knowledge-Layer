"""Database initialization and connection management.

Complete 12-table schema following Design.md:
  documents, pages, blocks, chunks, facts, entities,
  entity_aliases, fact_embeddings, candidate_pairs,
  relationships, jobs, llm_cache
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Schema ─────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- ═══════════════════════════════════════════════════════════════════
-- 1. documents
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS documents (
    id                  TEXT PRIMARY KEY,
    filename            TEXT NOT NULL,
    original_filename   TEXT NOT NULL,
    sha256              TEXT NOT NULL UNIQUE,
    file_size           INTEGER NOT NULL,
    page_count          INTEGER,
    title               TEXT,
    document_type       TEXT,
    published_date      TEXT,
    reporting_period    TEXT,
    status              TEXT NOT NULL DEFAULT 'uploaded',
    error_message       TEXT,
    metadata_json       TEXT,  -- flexible JSON metadata
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════════════
-- 2. pages
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS pages (
    id                  TEXT PRIMARY KEY,
    document_id         TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number         INTEGER NOT NULL,  -- 1-indexed
    width               REAL,
    height              REAL,
    raw_text            TEXT NOT NULL,
    cleaned_text        TEXT,
    text_quality        REAL,  -- 0.0-1.0
    is_scanned          INTEGER NOT NULL DEFAULT 0,
    metadata_json       TEXT,
    UNIQUE(document_id, page_number)
);

-- ═══════════════════════════════════════════════════════════════════
-- 3. blocks
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS blocks (
    id                  TEXT PRIMARY KEY,
    page_id             TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    block_index         INTEGER NOT NULL,
    block_type          TEXT NOT NULL DEFAULT 'unknown',
    text                TEXT NOT NULL,
    x0                  REAL,
    y0                  REAL,
    x1                  REAL,
    y1                  REAL,
    reading_order       INTEGER,
    content_hash        TEXT,
    metadata_json       TEXT  -- table headers/rows for table blocks
);

-- ═══════════════════════════════════════════════════════════════════
-- 4. chunks
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS chunks (
    id                  TEXT PRIMARY KEY,
    document_id         TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    sequence_index      INTEGER NOT NULL,
    start_page          INTEGER NOT NULL,
    end_page            INTEGER NOT NULL,
    block_ids_json      TEXT,          -- JSON array of block IDs
    heading_path_json   TEXT,          -- JSON array of heading strings
    text                TEXT NOT NULL,
    token_count         INTEGER,
    previous_chunk_id   TEXT,
    next_chunk_id       TEXT,
    has_table           INTEGER NOT NULL DEFAULT 0,
    has_low_quality_page INTEGER NOT NULL DEFAULT 0,
    content_hash        TEXT,
    extraction_status   TEXT NOT NULL DEFAULT 'pending'
);

-- ═══════════════════════════════════════════════════════════════════
-- 5. facts  (GENERIC: subject/predicate/value)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS facts (
    id                          TEXT PRIMARY KEY,
    document_id                 TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id                    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,

    -- Meaning
    subject                     TEXT NOT NULL,
    subject_mention             TEXT,
    entity_id                   TEXT REFERENCES entities(id) ON DELETE SET NULL,
    predicate                   TEXT NOT NULL,
    predicate_mention           TEXT,

    -- Value
    value_text                  TEXT NOT NULL,
    value_type                  TEXT NOT NULL DEFAULT 'text',
    numeric_value               REAL,
    normalized_numeric_value    REAL,
    unit                        TEXT,
    normalized_unit             TEXT,
    currency                    TEXT,

    -- Temporal context
    time_text                   TEXT,
    time_start                  TEXT,
    time_end                    TEXT,
    time_granularity            TEXT,

    -- Scope
    scope                       TEXT,
    geography                   TEXT,
    qualifiers_json             TEXT,          -- JSON array

    -- Provenance
    source_quote                TEXT NOT NULL,
    source_page_start           INTEGER NOT NULL,
    source_page_end             INTEGER NOT NULL,
    source_block_ids_json       TEXT,          -- JSON array

    -- Quality
    extraction_confidence       REAL NOT NULL DEFAULT 1.0,
    validation_status           TEXT NOT NULL DEFAULT 'validated',
    extraction_notes_json       TEXT,          -- JSON array

    created_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════════════
-- 6. entities
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS entities (
    id                  TEXT PRIMARY KEY,
    canonical_name      TEXT NOT NULL,
    entity_type         TEXT NOT NULL DEFAULT 'other',
    confidence          REAL NOT NULL DEFAULT 1.0,
    metadata_json       TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════════════
-- 7. entity_aliases
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS entity_aliases (
    id                  TEXT PRIMARY KEY,
    entity_id           TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias               TEXT NOT NULL,
    confidence          REAL NOT NULL DEFAULT 1.0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════════════
-- 8. fact_embeddings
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS fact_embeddings (
    id                  TEXT PRIMARY KEY,
    fact_id             TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    model               TEXT NOT NULL,
    dimensions          INTEGER NOT NULL,
    vector_blob         BLOB,
    content_hash        TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(fact_id, model)
);

-- ═══════════════════════════════════════════════════════════════════
-- 9. candidate_pairs
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS candidate_pairs (
    id                      TEXT PRIMARY KEY,
    fact_a_id               TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    fact_b_id               TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    same_document           INTEGER NOT NULL DEFAULT 0,

    entity_similarity       REAL,
    predicate_similarity    REAL,
    semantic_similarity     REAL,

    unit_compatible         INTEGER,
    period_compatible       INTEGER,
    scope_compatible        INTEGER,

    candidate_score         REAL NOT NULL DEFAULT 0.0,
    reason_json             TEXT,      -- JSON array of strings

    status                  TEXT NOT NULL DEFAULT 'pending',
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════════════
-- 10. relationships
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS relationships (
    id                          TEXT PRIMARY KEY,
    fact_a_id                   TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    fact_b_id                   TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    relationship_type           TEXT NOT NULL,
    confidence                  REAL NOT NULL DEFAULT 1.0,
    primary_dimension           TEXT,
    context_comparison_json     TEXT,       -- JSON dict
    explanation                 TEXT NOT NULL,
    evidence_fact_a             TEXT,
    evidence_fact_b             TEXT,
    reasoning_version           TEXT,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════════════
-- 11. jobs
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS jobs (
    id                  TEXT PRIMARY KEY,
    job_type            TEXT NOT NULL DEFAULT 'full',
    document_ids_json   TEXT,          -- JSON array of document IDs
    status              TEXT NOT NULL DEFAULT 'queued',
    progress            REAL NOT NULL DEFAULT 0.0,
    current_stage       TEXT,
    total_items         INTEGER NOT NULL DEFAULT 0,
    completed_items     INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    started_at          TEXT,
    completed_at        TEXT
);

-- ═══════════════════════════════════════════════════════════════════
-- 12. llm_cache
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS llm_cache (
    id                  TEXT PRIMARY KEY,
    operation           TEXT NOT NULL,
    model               TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    input_hash          TEXT NOT NULL,
    response_json       TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(operation, model, prompt_version, input_hash)
);

-- ═══════════════════════════════════════════════════════════════════
-- INDEXES
-- ═══════════════════════════════════════════════════════════════════

-- Document lookups
CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

-- Page lookups
CREATE INDEX IF NOT EXISTS idx_pages_document ON pages(document_id);
CREATE INDEX IF NOT EXISTS idx_pages_document_number ON pages(document_id, page_number);

-- Block lookups
CREATE INDEX IF NOT EXISTS idx_blocks_page ON blocks(page_id);
CREATE INDEX IF NOT EXISTS idx_blocks_content_hash ON blocks(content_hash);

-- Chunk lookups
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_status ON chunks(extraction_status);
CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks(content_hash);

-- Fact lookups
CREATE INDEX IF NOT EXISTS idx_facts_document ON facts(document_id);
CREATE INDEX IF NOT EXISTS idx_facts_chunk ON facts(chunk_id);
CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_validation ON facts(validation_status);
CREATE INDEX IF NOT EXISTS idx_facts_page_start ON facts(source_page_start);

-- Entity lookups
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

-- Entity alias lookups
CREATE INDEX IF NOT EXISTS idx_entity_aliases_entity ON entity_aliases(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_aliases_alias ON entity_aliases(alias);

-- Fact embedding lookups
CREATE INDEX IF NOT EXISTS idx_fact_embeddings_fact ON fact_embeddings(fact_id);
CREATE INDEX IF NOT EXISTS idx_fact_embeddings_hash ON fact_embeddings(content_hash);

-- Candidate pair lookups
CREATE INDEX IF NOT EXISTS idx_candidate_pairs_fact_a ON candidate_pairs(fact_a_id);
CREATE INDEX IF NOT EXISTS idx_candidate_pairs_fact_b ON candidate_pairs(fact_b_id);
CREATE INDEX IF NOT EXISTS idx_candidate_pairs_status ON candidate_pairs(status);

-- Relationship lookups
CREATE INDEX IF NOT EXISTS idx_relationships_fact_a ON relationships(fact_a_id);
CREATE INDEX IF NOT EXISTS idx_relationships_fact_b ON relationships(fact_b_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type);

-- Job lookups
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

-- LLM cache lookups
CREATE INDEX IF NOT EXISTS idx_llm_cache_lookup
    ON llm_cache(operation, model, prompt_version, input_hash);
"""

# ── All expected table names (for test assertions) ─────────────────

ALL_TABLES = frozenset({
    "documents",
    "pages",
    "blocks",
    "chunks",
    "facts",
    "entities",
    "entity_aliases",
    "fact_embeddings",
    "candidate_pairs",
    "relationships",
    "jobs",
    "llm_cache",
})


def get_db_path() -> Path:
    """Return the resolved path to the SQLite database file."""
    settings = get_settings()
    db_path = Path(settings.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def init_db(db_path: Optional[str | Path] = None) -> None:
    """Create tables if they do not exist (synchronous, used at startup)."""
    target_path = Path(db_path) if db_path else get_db_path()
    logger.info("Initializing database at %s", target_path)
    conn = sqlite3.connect(str(target_path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        logger.info("Database schema ready — %d tables", len(ALL_TABLES))
    finally:
        conn.close()


def get_connection(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    """Return a new synchronous SQLite connection with WAL and FK enabled."""
    target_path = Path(db_path) if db_path else get_db_path()
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    row = conn.execute("SELECT count(*) as c FROM sqlite_master WHERE type='table' AND name='documents'").fetchone()
    if not row or row["c"] == 0:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    return conn
