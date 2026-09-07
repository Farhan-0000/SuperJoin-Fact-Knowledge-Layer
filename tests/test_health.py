"""Tests for the /health endpoint."""

from __future__ import annotations


def test_health_returns_ok(client):
    """GET /health should return 200 with status=ok."""
    resp = client.get("/health")
    assert resp.status_code == 200

    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert data["database"] == "connected"
    assert data["documents_count"] == 0


def test_health_schema_fields(client):
    """Health response must contain all expected fields."""
    resp = client.get("/health")
    data = resp.json()

    expected_keys = {"status", "version", "database", "documents_count"}
    assert expected_keys == set(data.keys())
