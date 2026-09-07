"""Shared pytest fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.fixtures_pdf import create_sample_pdf


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ensure every test uses a throwaway storage directory and database."""
    storage = tmp_path / "storage"
    storage.mkdir()
    db_path = storage / "test.db"

    monkeypatch.setenv("STORAGE_DIR", str(storage))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")

    # Clear the cached settings so each test picks up its own env
    from app.config import get_settings
    get_settings.cache_clear()

    yield

    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    """Return a TestClient wired to a fresh app instance."""
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Fixture returning raw PDF bytes with 4 pages."""
    return create_sample_pdf()
