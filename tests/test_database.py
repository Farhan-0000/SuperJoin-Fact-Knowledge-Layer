"""Tests for database initialization."""

from __future__ import annotations

import sqlite3

from app.db.database import init_db, get_connection


def test_init_db_creates_tables():
    """init_db should create all expected tables."""
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cursor.fetchall()}
    finally:
        conn.close()

    expected = {"documents", "chunks", "facts", "fact_relationships", "extraction_failures"}
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


def test_init_db_idempotent():
    """Calling init_db twice should not raise."""
    init_db()
    init_db()  # should not error


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
