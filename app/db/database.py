"""Database initialization and connection management."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Schema ─────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    original_name   TEXT NOT NULL,
    file_hash       TEXT NOT NULL UNIQUE,
    size_bytes      INTEGER NOT NULL,
    page_count      INTEGER,
    status          TEXT NOT NULL DEFAULT 'uploaded',  -- uploaded | processing | ready | error
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number     INTEGER NOT NULL,
    chunk_index     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    char_offset     INTEGER,
    char_length     INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS facts (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id        TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    claim           TEXT NOT NULL,
    source_quote    TEXT NOT NULL,
    page_number     INTEGER NOT NULL,
    category        TEXT,
    confidence      REAL NOT NULL DEFAULT 1.0,
    normalized_value TEXT,
    raw_value       TEXT,
    unit            TEXT,
    time_reference  TEXT,
    entity          TEXT,
    extraction_model TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fact_relationships (
    id              TEXT PRIMARY KEY,
    fact_id_a       TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    fact_id_b       TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    relationship    TEXT NOT NULL,  -- corroborates | contradicts | contextualizes
    explanation     TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    reasoning_model TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extraction_failures (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id        TEXT REFERENCES chunks(id) ON DELETE SET NULL,
    failure_type    TEXT NOT NULL,
    description     TEXT NOT NULL,
    raw_input       TEXT,
    raw_output      TEXT,
    handling        TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_facts_document ON facts(document_id);
CREATE INDEX IF NOT EXISTS idx_facts_chunk ON facts(chunk_id);
CREATE INDEX IF NOT EXISTS idx_fact_relationships_a ON fact_relationships(fact_id_a);
CREATE INDEX IF NOT EXISTS idx_fact_relationships_b ON fact_relationships(fact_id_b);
CREATE INDEX IF NOT EXISTS idx_extraction_failures_document ON extraction_failures(document_id);
"""


def get_db_path() -> Path:
    """Return the resolved path to the SQLite database file."""
    settings = get_settings()
    db_path = Path(settings.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def init_db() -> None:
    """Create tables if they do not exist (synchronous, used at startup)."""
    db_path = get_db_path()
    logger.info("Initializing database at %s", db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        logger.info("Database schema ready")
    finally:
        conn.close()


def get_connection() -> sqlite3.Connection:
    """Return a new synchronous SQLite connection (for simple queries)."""
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
