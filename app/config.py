"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from functools import lru_cache

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration. Values come from environment / .env file."""

    # ── LLM ────────────────────────────────────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_base_url: Optional[str] = Field(default=None, description="Base URL for OpenAI-compatible providers like Gemini")
    gemini_api_key: str = Field(default="", description="Gemini API key")
    extraction_model: str = Field(default="gpt-4o", description="Model for fact extraction")
    relationship_model: str = Field(default="gpt-4o", description="Model for relationship reasoning")
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Model for embedding generation"
    )

    @property
    def is_gemini(self) -> bool:
        """Detect if configured key is a Gemini API key or base_url is Google."""
        key = self.gemini_api_key or self.openai_api_key
        url = self.openai_base_url or ""
        return (
            bool(self.gemini_api_key)
            or key.startswith("AQ.")
            or key.startswith("AIzaSy")
            or "googleapis.com" in url
        )

    @property
    def effective_api_key(self) -> str:
        return self.gemini_api_key or self.openai_api_key

    @property
    def resolved_base_url(self) -> Optional[str]:
        if self.openai_base_url:
            return self.openai_base_url
        if self.is_gemini:
            return "https://generativelanguage.googleapis.com/v1beta/openai/"
        return None

    @property
    def resolved_extraction_model(self) -> str:
        if self.is_gemini and (self.extraction_model.startswith("gpt-") or self.extraction_model in ("gpt-4o", "gpt-4o-mini", "gemini-3.6-flash")):
            return "gemini-3.1-flash-lite"
        return self.extraction_model

    @property
    def resolved_relationship_model(self) -> str:
        if self.is_gemini and (self.relationship_model.startswith("gpt-") or self.relationship_model in ("gpt-4o", "gpt-4o-mini", "gemini-3.6-flash")):
            return "gemini-3.1-flash-lite"
        return self.relationship_model

    @property
    def resolved_embedding_model(self) -> str:
        if self.is_gemini and "text-embedding-3" in self.embedding_model:
            return "gemini-embedding-001"
        return self.embedding_model

    @property
    def resolved_max_llm_concurrency(self) -> int:
        """Keep concurrency conservative on free-tier rate limits.

        Gemini free tier allows only 15 RPM.  Serializing to concurrency=1
        combined with inter-call pacing guarantees we stay under the limit.
        """
        if self.is_gemini:
            return 1
        return self.max_llm_concurrency

    # ── Candidate Generation ───────────────────────────────────────
    candidate_min_score: float = Field(
        default=0.60, ge=0.0, le=1.0, description="Minimum candidate score to retain pair"
    )
    candidate_top_k: int = Field(
        default=10, ge=1, le=100, description="Max candidate pairs to retain per fact"
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

    embedding_batch_size: int = Field(default=32, ge=1, le=256, description="Batch size for embedding generation")
    ocr_provider: str = Field(default="pymupdf_ocr", description="OCR provider name")
    low_quality_threshold: float = Field(default=0.30, ge=0.0, le=1.0, description="Threshold for low text density")

    # ── Application ───────────────────────────────────────────────
    log_level: str = Field(default="INFO", description="Logging level")
    app_host: str = Field(default="0.0.0.0", description="Host to bind")
    app_port: int = Field(default=8000, ge=1, le=65535, description="Port to bind")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
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
