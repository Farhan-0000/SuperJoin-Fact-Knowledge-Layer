"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.config import get_settings
from app.db.database import init_db
from app.logging_config import setup_logging
from app.api.health import router as health_router
from app.api.documents import router as documents_router
from app.api.facts import router as facts_router
from app.api.candidates import router as candidates_router
from app.api.relationships import router as relationships_router

from app.api.v1 import v1_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title="Fact Knowledge Layer",
        description=(
            "Extracts, normalizes, and reconciles facts from PDF documents "
            "with full provenance tracking."
        ),
        version="0.1.0",
    )

    # ── Startup / Shutdown ─────────────────────────────────────────

    @app.on_event("startup")
    def on_startup() -> None:
        logger.info("Starting Fact Knowledge Layer v0.1.0")
        settings.storage_path  # ensure directory exists
        init_db()
        logger.info("Application ready")

    # ── Routers ────────────────────────────────────────────────────

    app.include_router(health_router)
    app.include_router(v1_router, prefix="/v1")
    app.include_router(documents_router, prefix="/api")
    app.include_router(facts_router, prefix="/api")
    app.include_router(candidates_router, prefix="/api")
    app.include_router(relationships_router, prefix="/api")

    return app
