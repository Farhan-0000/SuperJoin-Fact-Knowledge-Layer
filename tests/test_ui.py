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


def test_ui_data_service_low_quality_pages(tmp_path: Path):
    """Verify get_low_quality_pages correctly filters scanned and low-quality pages."""
    db_file = str(tmp_path / "test_ui_pages.db")
    init_db(db_file)
    conn = get_connection(db_file)
    conn.execute(
        "INSERT INTO documents (id, filename, original_filename, sha256, file_size) VALUES ('d-lq', 'scanned.pdf', 'scanned.pdf', 'h_lq', 500)"
    )
    conn.execute(
        "INSERT INTO pages (id, document_id, page_number, raw_text, text_quality, is_scanned) VALUES "
        "('p-1', 'd-lq', 1, 'good page text with high confidence', 0.95, 0), "
        "('p-2', 'd-lq', 2, 'blurry low quality scan', 0.15, 0), "
        "('p-3', 'd-lq', 3, '', 0.0, 1)"
    )
    conn.commit()
    conn.close()

    service = UIDataService(db_path=db_file)
    low_pages = service.get_low_quality_pages()
    assert len(low_pages) == 2
    page_numbers = {p["page_number"] for p in low_pages}
    assert page_numbers == {2, 3}


def test_relationships_view_supports_dict_context_comp(tmp_path: Path):
    """Verify that get_relationships_enriched parses dict context_comparison_json and prepares it for rendering."""
    import json
    db_file = str(tmp_path / "test_ui_rel_dict.db")
    init_db(db_file)
    conn = get_connection(db_file)
    conn.execute(
        "INSERT INTO documents (id, filename, original_filename, sha256, file_size) VALUES ('d-1', 'doc1.pdf', 'doc1.pdf', 'h1', 100)"
    )
    conn.execute(
        "INSERT INTO chunks (id, document_id, sequence_index, start_page, end_page, text) VALUES ('c-1', 'd-1', 0, 1, 1, 'text')"
    )
    conn.execute(
        """INSERT INTO facts (
            id, document_id, chunk_id, subject, predicate, value_text, value_type, currency, normalized_numeric_value, time_text, source_quote, source_page_start, source_page_end
        ) VALUES
        ('f-1', 'd-1', 'c-1', 'Delhivery', 'revenue', '8142 Cr', 'currency', 'INR', 81420000000.0, 'FY24', 'quote 1', 1, 1),
        ('f-2', 'd-1', 'c-1', 'Delhivery', 'revenue', '2190 Cr', 'currency', 'INR', 21900000000.0, 'Q4 FY24', 'quote 2', 1, 1)"""
    )
    context_dict = {
        "entity_a": "Delhivery",
        "entity_b": "Delhivery",
        "entity_match": True,
        "predicate_a": "revenue",
        "predicate_b": "revenue",
        "predicate_match": True,
        "period_a": "FY24",
        "period_b": "Q4 FY24",
        "period_match": False,
        "scope_a": "consolidated",
        "scope_b": "consolidated",
        "scope_match": True,
        "geography_a": "India",
        "geography_b": "India",
        "geography_match": True,
    }
    conn.execute(
        """INSERT INTO relationships (
            id, fact_a_id, fact_b_id, relationship_type, confidence, primary_dimension, context_comparison_json, explanation, evidence_fact_a, evidence_fact_b
        ) VALUES ('rel-dict-1', 'f-1', 'f-2', 'reconciles', 0.95, 'time', ?, 'Time period variance', 'quote 1', 'quote 2')""",
        (json.dumps(context_dict),),
    )
    conn.commit()
    conn.close()

    service = UIDataService(db_path=db_file)
    rels = service.get_relationships_enriched(limit=10)
    assert len(rels) == 1
    assert isinstance(rels[0]["context_comp"], dict)
    assert rels[0]["context_comp"]["entity_a"] == "Delhivery"


