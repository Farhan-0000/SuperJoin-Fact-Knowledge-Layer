"""Test suite for Phase 10 — Streamlit UI data service and components."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.db.database import get_connection, init_db
from tests.fixtures_pdf import create_sample_pdf
from ui.data_service import UIDataService, get_data_service
from ui.styles import inject_custom_css, render_badge, render_stat_card
from ui.views.failures import render_failures_view
from ui.views.facts import render_facts_view
from ui.views.knowledge import render_knowledge_view
from ui.views.processing import render_processing_view
from ui.views.relationships import render_relationships_view
from ui.views.upload import render_upload_view


def test_ui_data_service_initialization():
    """Verify UIDataService initializes and can query knowledge summary."""
    init_db()
    service = UIDataService()
    summary = service.get_knowledge_summary()
    assert isinstance(summary, dict)
    assert "documents" in summary
    assert "facts" in summary
    assert "relationships" in summary


def test_ui_data_service_seed_demo_dataset():
    """Verify seed_demo_dataset populates documents, entities, facts, relationships and completed job."""
    init_db()
    service = UIDataService()
    service.seed_demo_dataset()

    # Verify documents count
    docs = service.get_documents()
    assert len(docs) >= 3
    filenames = [d["original_filename"] for d in docs]
    assert "annual_report.pdf" in filenames
    assert "investor_report.pdf" in filenames
    assert "sustainability_report.pdf" in filenames

    # Verify facts count
    facts = service.get_facts(limit=50)
    assert len(facts) >= 6

    # Verify relationships count and types
    rels = service.get_relationships_enriched(limit=50)
    assert len(rels) >= 5
    types = {r["relationship_type"] for r in rels}
    assert "reconciles" in types
    assert "corroborates" in types
    assert "contradicts" in types
    assert "uncertain" in types

    # Verify knowledge summary
    stats = service.get_knowledge_summary()
    assert stats["documents"] >= 3
    assert stats["corroborations"] >= 2
    assert stats["contradictions"] >= 1
    assert stats["reconciliations"] >= 2
    assert stats["uncertain"] >= 1

    # Verify failures view data
    rejected = service.get_rejected_facts()
    assert len(rejected) >= 1
    warnings = service.get_warning_facts()
    assert len(warnings) >= 1
    uncertain = service.get_uncertain_relationships()
    assert len(uncertain) >= 1


def test_ui_data_service_upload_and_deduplication(sample_pdf_bytes: bytes):
    """Verify upload_pdf_bytes handles ingestion and duplicate SHA-256 reuse."""
    init_db()
    service = UIDataService()

    # 1. First upload
    doc1, is_new1 = service.upload_pdf_bytes(sample_pdf_bytes, "report1.pdf")
    assert is_new1 is True
    assert doc1["original_filename"] == "report1.pdf"

    # 2. Second upload with identical bytes
    doc2, is_new2 = service.upload_pdf_bytes(sample_pdf_bytes, "report2.pdf")
    assert is_new2 is False
    assert doc2["id"] == doc1["id"]

    # Verify total documents count is 1
    assert service.get_document_count() == 1


def test_ui_data_service_jobs():
    """Verify starting and querying pipeline jobs."""
    init_db()
    service = UIDataService()
    service.seed_demo_dataset()
    docs = service.get_documents()
    doc_ids = [d["id"] for d in docs[:2]]

    with patch("app.workers.job_runner.LocalJobRunner.run_pipeline"):
        job_id = service.start_pipeline_job(doc_ids, mode="full")
    assert job_id.startswith("job_")

    job = service.get_job(job_id)
    assert job is not None
    assert job["id"] == job_id
    assert job["status"] in ("queued", "running", "completed")

    jobs = service.get_jobs()
    assert len(jobs) >= 1


def test_ui_styles_and_badges():
    """Verify HTML component generators for badges and stat cards."""
    badge = render_badge("RECONCILES")
    assert "rel-badge reconciles" in badge
    assert "RECONCILES" in badge

    stat = render_stat_card("Corroborations", 31, "Facts that agree", "corroborates", "✓")
    assert "stat-card corroborates" in stat
    assert "31" in stat
    assert "Corroborations" in stat


def test_ui_view_functions_callable():
    """Verify that all view rendering functions are cleanly importable and callable."""
    assert callable(render_upload_view)
    assert callable(render_processing_view)
    assert callable(render_knowledge_view)
    assert callable(render_facts_view)
    assert callable(render_relationships_view)
    assert callable(render_failures_view)
    assert callable(inject_custom_css)
