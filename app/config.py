"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration. Values come from environment / .env file."""

    # ── LLM ────────────────────────────────────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API key")
    extraction_model: str = Field(default="gpt-4o", description="Model for fact extraction")
    relationship_model: str = Field(default="gpt-4o", description="Model for relationship reasoning")
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Model for embedding generation"
    )

    # ── Storage ────────────────────────────────────────────────────
    storage_dir: str = Field(default="./storage", description="Directory for uploaded files")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./storage/facts.db",
        description="SQLite database URL",
    )

    # ── Concurrency & Limits ──────────────────────────────────────
    max_llm_concurrency: int = Field(default=4, ge=1, le=32, description="Max concurrent LLM calls")
    max_file_size_mb: int = Field(default=50, ge=1, le=500, description="Max upload file size in MB")

    # ── Application ───────────────────────────────────────────────
    log_level: str = Field(default="INFO", description="Logging level")
    app_host: str = Field(default="0.0.0.0", description="Host to bind")
    app_port: int = Field(default=8000, ge=1, le=65535, description="Port to bind")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    @property
    def storage_path(self) -> Path:
        """Resolved, absolute storage directory path."""
        p = Path(self.storage_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def sqlite_path(self) -> str:
        """Extract the raw sqlite file path from the database URL."""
        # database_url format: sqlite+aiosqlite:///./storage/facts.db
        prefix = "sqlite+aiosqlite:///"
        if self.database_url.startswith(prefix):
            return self.database_url[len(prefix):]
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of application settings."""
    return Settings()
