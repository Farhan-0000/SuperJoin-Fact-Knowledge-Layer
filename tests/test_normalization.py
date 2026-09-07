"""Test suite for Phase 6 — Normalization, Entity Resolution, and Deduplication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db.database import get_connection, init_db
from app.models.schemas import EntityType, FactSchema, TimeGranularity, ValidationStatus, ValueType
from app.services.normalization.dates import normalize_date_period
from app.services.normalization.deduplication import deduplicate_facts
from app.services.normalization.entities import EntityResolver
from app.services.normalization.numeric import normalize_numeric
from app.services.normalization.pipeline import NormalizationPipeline
from app.services.normalization.predicates import normalize_predicate


# ── 1. Numeric Normalization Tests ───────────────────────────────────


def test_numeric_normalization_1_2_billion_equals_1200_million():
    """Verify that 1.2 billion and 1,200 million evaluate to exactly the same normalized numeric value."""
    res_billions = normalize_numeric("1.2 billion")
    res_millions = normalize_numeric("1,200 million")

    assert res_billions.normalized_numeric == 1_200_000_000.0
    assert res_millions.normalized_numeric == 1_200_000_000.0
    assert res_billions.normalized_numeric == res_millions.normalized_numeric

    # Test with currency: $1.2B == USD 1,200M
    res_b_curr = normalize_numeric("$1.2B")
    res_m_curr = normalize_numeric("USD 1,200M")
    assert res_b_curr.normalized_numeric == res_m_curr.normalized_numeric == 1_200_000_000.0
    assert res_b_curr.currency == res_m_curr.currency == "USD"


def test_numeric_normalization_percentage():
    """Verify that 2.5% is normalized to ratio 0.025 and unit %."""
    res_pct = normalize_numeric("2.5%")
    assert res_pct.raw_numeric == 2.5
    assert res_pct.normalized_numeric == 0.025
    assert res_pct.unit == "%"
    assert res_pct.normalized_unit == "%"
    assert res_pct.value_type == ValueType.PERCENTAGE

    # Spelled out "percent"
    res_words = normalize_numeric("2.5 percent")
    assert res_words.normalized_numeric == 0.025
    assert res_words.value_type == ValueType.PERCENTAGE


def test_numeric_normalization_comma_separated_and_currency_symbols():
    """Verify comma-separated numbers and standard currency symbols."""
    # Comma separation
    res_comma = normalize_numeric("1,200,500.50")
    assert res_comma.normalized_numeric == 1200500.50

    # Euro symbol
    res_eur = normalize_numeric("€45M")
    assert res_eur.normalized_numeric == 45_000_000.0
    assert res_eur.currency == "EUR"

    # British Pound
    res_gbp = normalize_numeric("£10.5 billion")
    assert res_gbp.normalized_numeric == 10_500_000_000.0
    assert res_gbp.currency == "GBP"

    # Japanese Yen
    res_jpy = normalize_numeric("¥500,000")
    assert res_jpy.normalized_numeric == 500_000.0
    assert res_jpy.currency == "JPY"


def test_numeric_normalization_ratios():
    """Verify ratios are parsed safely."""
    res_ratio = normalize_numeric("1:2")
    assert res_ratio.normalized_numeric == 0.5
    assert res_ratio.value_type == ValueType.RANGE


# ── 2. Date and Period Normalization Tests ────────────────────────────


def test_date_normalization_fy2025_preservation():
    """Verify FY2025 preservation without hallucinating unverified calendar bounds."""
    # Without fiscal year context: preserve time_text and granularity, leave bounds None
    res = normalize_date_period("FY2025")
    assert res.time_text == "FY2025"
    assert res.time_granularity == TimeGranularity.FISCAL_YEAR
    assert res.time_start is None
    assert res.time_end is None

    # Variants (e.g. "Fiscal Year 2025", "FY 25")
    res_var1 = normalize_date_period("Fiscal Year 2025")
    assert res_var1.time_text == "FY2025"
    res_var2 = normalize_date_period("FY25")
    assert res_var2.time_text == "FY2025"

    # With supported document context (e.g. March 31 year end)
    doc_ctx = {"fiscal_year_end": "03-31"}
    res_ctx = normalize_date_period("FY2025", document_context=doc_ctx)
    assert res_ctx.time_text == "FY2025"
    assert res_ctx.time_start == "2024-04-01"
    assert res_ctx.time_end == "2025-03-31"


def test_date_normalization_quarters_and_ranges():
    """Verify calendar quarters, months, and year ranges."""
    # Calendar quarter
    res_q1 = normalize_date_period("Q1 2024")
    assert res_q1.time_text == "Q1 2024"
    assert res_q1.time_start == "2024-01-01"
    assert res_q1.time_end == "2024-03-31"

    # Month and year
    res_month = normalize_date_period("March 2024")
    assert res_month.time_text == "March 2024"
    assert res_month.time_start == "2024-03-01"
    assert res_month.time_end == "2024-03-31"
    assert res_month.time_granularity == TimeGranularity.MONTH

    # Year range
    res_range = normalize_date_period("2023 - 2025")
    assert res_range.time_text == "2023-2025"
    assert res_range.time_start == "2023-01-01"
    assert res_range.time_end == "2025-12-31"


# ── 3. Predicate Normalization Tests ──────────────────────────────────


def test_predicate_normalization_never_forces_revenue_sales_equivalence():
    """Verify predicate standardization keeps revenue and sales distinct."""
    res_rev1 = normalize_predicate("total_revenue")
    res_rev2 = normalize_predicate("Gross Revenue")
    assert res_rev1.canonical_predicate == "revenue"
    assert res_rev2.canonical_predicate == "revenue"

    res_sales1 = normalize_predicate("net_sales")
    res_sales2 = normalize_predicate("Product Sales")
    assert res_sales1.canonical_predicate == "sales"
    assert res_sales2.canonical_predicate == "sales"

    # CRITICAL: revenue and sales must remain distinct canonical predicates
    assert res_rev1.canonical_predicate != res_sales1.canonical_predicate


# ── 4. Entity Resolution Tests ────────────────────────────────────────


def test_entity_resolution_stem_matching_and_alias_preservation():
    """Verify legal suffixes (Corp., Inc., Corporation) resolve to the same entity and preserve aliases."""
    init_db()
    resolver = EntityResolver()

    # First mention: Acme Corporation
    ent1 = resolver.resolve_entity("Acme Corporation", EntityType.ORGANIZATION)
    assert ent1.is_new is True

    # Second mention: Acme Corp. (legal suffix variation)
    ent2 = resolver.resolve_entity("Acme Corp.", EntityType.ORGANIZATION)
    assert ent2.is_new is False
    assert ent2.entity_id == ent1.entity_id

    # Verify alias saved in database
    conn = get_connection()
    aliases = conn.execute(
        "SELECT alias FROM entity_aliases WHERE entity_id = ?", (ent1.entity_id,)
    ).fetchall()
    conn.close()
    alias_names = [a["alias"] for a in aliases]
    assert "Acme Corporation" in alias_names
    assert "Acme Corp." in alias_names


def test_uncertain_entity_matches_remaining_uncertain():
    """Verify generic or ambiguous entity mentions remain uncertain and do NOT force-merge."""
    init_db()
    resolver = EntityResolver()

    # Generic term: "the company"
    ent_generic = resolver.resolve_entity("the company", EntityType.ORGANIZATION)
    assert ent_generic.is_uncertain is True
    assert ent_generic.confidence < 0.7

    # Distinct entities with shared keywords
    ent_a = resolver.resolve_entity("Beta Health Group", EntityType.ORGANIZATION)
    ent_b = resolver.resolve_entity("Beta Aviation Holdings", EntityType.ORGANIZATION)
    assert ent_a.entity_id != ent_b.entity_id, "Distinct entities sharing common word must NOT merge"


# ── 5. Same-Document Fact Deduplication Tests ─────────────────────────


def test_duplicate_facts_with_different_periods_not_merging():
    """Verify identical values across different periods (e.g. FY2024 vs FY2025) are NOT merged."""
    fact_fy24 = FactSchema(
        id="f1",
        document_id="doc-1",
        chunk_id="chunk-1",
        subject="Acme Corporation",
        predicate="revenue",
        value_text="$120M",
        normalized_numeric_value=120_000_000.0,
        normalized_unit="USD",
        time_text="FY2024",
        scope="consolidated",
        source_quote="FY2024 revenue was $120M.",
        source_page_start=1,
        source_page_end=1,
        source_block_ids_json=json.dumps(["b1"]),
    )

    fact_fy25 = FactSchema(
        id="f2",
        document_id="doc-1",
        chunk_id="chunk-2",
        subject="Acme Corporation",
        predicate="revenue",
        value_text="$120M",
        normalized_numeric_value=120_000_000.0,
        normalized_unit="USD",
        time_text="FY2025",
        scope="consolidated",
        source_quote="FY2025 revenue was $120M.",
        source_page_start=2,
        source_page_end=2,
        source_block_ids_json=json.dumps(["b2"]),
    )

    deduped = deduplicate_facts([fact_fy24, fact_fy25])
    assert len(deduped) == 2, "Facts with different periods must NOT merge even if values are equal"


def test_duplicate_facts_with_equivalent_evidence_merging():
    """Verify identical facts in the same document merge into a single fact

    while preserving all source evidence locations (pages and blocks).
    """
    fact_1 = FactSchema(
        id="f1",
        document_id="doc-1",
        chunk_id="chunk-1",
        subject="Acme Corporation",
        predicate="revenue",
        value_text="$120 million",
        normalized_numeric_value=120_000_000.0,
        normalized_unit="USD",
        time_text="FY2025",
        scope="consolidated",
        source_quote="Revenue reached $120 million in FY2025.",
        source_page_start=1,
        source_page_end=1,
        source_block_ids_json=json.dumps(["block_1"]),
        extraction_confidence=0.90,
    )

    fact_2 = FactSchema(
        id="f2",
        document_id="doc-1",
        chunk_id="chunk-3",
        subject="Acme Corporation",
        predicate="revenue",
        value_text="$120M",
        normalized_numeric_value=120_000_000.0,
        normalized_unit="USD",
        time_text="FY2025",
        scope="consolidated",
        source_quote="As previously noted, FY2025 revenue was $120M.",
        source_page_start=4,
        source_page_end=4,
        source_block_ids_json=json.dumps(["block_10"]),
        extraction_confidence=0.95,
    )

    deduped = deduplicate_facts([fact_1, fact_2])
    assert len(deduped) == 1, "Equivalent facts must merge"

    merged = deduped[0]
    # Verify all evidence locations are preserved
    assert merged.source_page_start == 1
    assert merged.source_page_end == 4
    merged_blocks = json.loads(merged.source_block_ids_json)
    assert "block_1" in merged_blocks
    assert "block_10" in merged_blocks
    assert merged.extraction_confidence == 0.95
    # Verify quotes preserved
    assert "Revenue reached $120 million" in merged.source_quote
    assert "revenue was $120M" in merged.source_quote


# ── 6. End-to-End Pipeline Tests ──────────────────────────────────────


def test_normalization_pipeline_end_to_end():
    """Verify NormalizationPipeline coordinates numeric, date, predicate, entity, and deduplication."""
    init_db()
    pipeline = NormalizationPipeline()

    fact_raw = FactSchema(
        id="f_test",
        document_id="doc_test",
        chunk_id="c_test",
        subject="Acme Corp.",
        subject_mention="Acme Corp.",
        predicate="Total Revenue",
        value_text="1.2 billion USD",
        time_text="FY 2025",
        source_quote="Acme Corp. total revenue was 1.2 billion USD in FY 2025.",
        source_page_start=1,
        source_page_end=1,
        source_block_ids_json=json.dumps(["b1"]),
    )

    normalized = pipeline.normalize_fact(fact_raw)

    assert normalized.subject == "Acme Corp."
    assert normalized.predicate == "revenue"  # canonical
    assert normalized.normalized_numeric_value == 1_200_000_000.0
    assert normalized.currency == "USD"
    assert normalized.time_text == "FY2025"
    assert normalized.time_granularity == TimeGranularity.FISCAL_YEAR
    assert normalized.entity_id is not None
