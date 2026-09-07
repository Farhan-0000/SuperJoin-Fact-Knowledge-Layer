"""Tests for application configuration."""

from __future__ import annotations

import os

from app.config import Settings


def test_default_settings():
    """Settings should load with sensible defaults."""
    s = Settings(openai_api_key="sk-test", _env_file=None)
    assert s.extraction_model == "gpt-4o"
    assert s.max_llm_concurrency == 4
    assert s.max_file_size_mb == 50
    assert s.max_file_size_bytes == 50 * 1024 * 1024


def test_storage_path_created(tmp_path):
    """storage_path property should create the directory."""
    sd = tmp_path / "new_storage"
    s = Settings(openai_api_key="sk-test", storage_dir=str(sd))
    resolved = s.storage_path
    assert resolved.exists()
    assert resolved.is_dir()


def test_max_concurrency_bounds():
    """max_llm_concurrency must be within [1, 32]."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(openai_api_key="sk-test", max_llm_concurrency=0)

    with pytest.raises(ValidationError):
        Settings(openai_api_key="sk-test", max_llm_concurrency=33)
