"""Tests for Pydantic model validation and serialization."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    BlockSchema,
    BlockType,
    CandidatePairSchema,
    CandidateStatus,
    ChunkSchema,
    ChunkStatus,
    DocumentSchema,
    DocumentStatus,
    EntityAliasSchema,
    EntitySchema,
    EntityType,
    FactEmbeddingSchema,
    FactSchema,
    HealthResponse,
    JobSchema,
    JobStatus,
    JobType,
    LLMCacheSchema,
    PageSchema,
    PrimaryDimension,
    RelationshipSchema,
    RelationshipType,
    TimeGranularity,
    ValidationStatus,
    ValueType,
)


# ── Document ───────────────────────────────────────────────────────


class TestDocumentSchema:
    def test_valid_document(self):
        doc = DocumentSchema(
            id="doc-1",
            filename="report.pdf",
            original_filename="Annual Report 2025.pdf",
            sha256="abc123",
            file_size=1024,
            page_count=50,
            status=DocumentStatus.UPLOADED,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        assert doc.filename == "report.pdf"
        assert doc.status == DocumentStatus.UPLOADED

    def test_optional_fields_default_none(self):
        doc = DocumentSchema(
            id="d", filename="f.pdf", original_filename="f.pdf",
            sha256="h", file_size=1, created_at="t", updated_at="t",
        )
        assert doc.title is None
        assert doc.document_type is None
        assert doc.published_date is None

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            DocumentSchema(
                id="d", filename="f.pdf", original_filename="f.pdf",
                sha256="h", file_size=1, status="bogus",
                created_at="t", updated_at="t",
            )


# ── Page ───────────────────────────────────────────────────────────


class TestPageSchema:
    def test_valid_page(self):
        page = PageSchema(
            id="p-1", document_id="doc-1", page_number=1,
            width=612.0, height=792.0, raw_text="Hello world",
        )
        assert page.page_number == 1
        assert page.is_scanned is False

    def test_scanned_flag(self):
        page = PageSchema(
            id="p-1", document_id="doc-1", page_number=1,
            raw_text="", is_scanned=True,
        )
        assert page.is_scanned is True


# ── Block ──────────────────────────────────────────────────────────


class TestBlockSchema:
    def test_valid_block_with_bbox(self):
        block = BlockSchema(
            id="b-1", page_id="p-1", block_index=0,
            block_type=BlockType.PARAGRAPH, text="Hello",
            x0=10.0, y0=20.0, x1=300.0, y1=50.0,
        )
        assert block.block_type == BlockType.PARAGRAPH

    def test_table_block_with_metadata(self):
        meta = json.dumps({"headers": ["Year", "Revenue"], "rows": [["2025", "$8B"]]})
        block = BlockSchema(
            id="b-2", page_id="p-1", block_index=1,
            block_type=BlockType.TABLE, text="Year Revenue 2025 $8B",
            metadata_json=meta,
        )
        parsed = json.loads(block.metadata_json)
        assert parsed["headers"] == ["Year", "Revenue"]


# ── Chunk ──────────────────────────────────────────────────────────


class TestChunkSchema:
    def test_valid_chunk(self):
        chunk = ChunkSchema(
            id="c-1", document_id="doc-1", sequence_index=0,
            start_page=1, end_page=2, text="Chunk text",
            token_count=50,
        )
        assert chunk.extraction_status == ChunkStatus.PENDING
        assert chunk.has_table is False

    def test_chunk_with_block_ids(self):
        ids = json.dumps(["b1", "b2"])
        chunk = ChunkSchema(
            id="c-1", document_id="doc-1", sequence_index=0,
            start_page=1, end_page=1, text="t", block_ids_json=ids,
        )
        assert json.loads(chunk.block_ids_json) == ["b1", "b2"]


# ── Fact (GENERIC) ─────────────────────────────────────────────────


class TestFactSchema:
    def test_generic_fact_creation(self):
        """Facts use subject/predicate/value — no domain-specific fields."""
        fact = FactSchema(
            id="f-1", document_id="doc-1", chunk_id="c-1",
            subject="Acme Corp",
            predicate="annual revenue",
            value_text="$8.2 billion",
            value_type=ValueType.CURRENCY,
            numeric_value=8.2e9,
            normalized_numeric_value=8200000000.0,
            unit="USD", currency="USD",
            time_text="FY2025",
            time_start="2024-04-01", time_end="2025-03-31",
            time_granularity=TimeGranularity.FISCAL_YEAR,
            source_quote="Revenue for fiscal year 2025 was $8.2 billion.",
            source_page_start=47, source_page_end=47,
            extraction_confidence=0.95,
        )
        assert fact.subject == "Acme Corp"
        assert fact.predicate == "annual revenue"
        assert fact.value_type == ValueType.CURRENCY

    def test_fact_confidence_bounds(self):
        """Confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            FactSchema(
                id="f", document_id="d", chunk_id="c",
                subject="X", predicate="p", value_text="v",
                source_quote="q", source_page_start=1, source_page_end=1,
                extraction_confidence=1.5,
            )

    def test_fact_with_qualifiers(self):
        qualifiers = json.dumps(["consolidated", "audited"])
        fact = FactSchema(
            id="f-1", document_id="d", chunk_id="c",
            subject="X", predicate="p", value_text="v",
            source_quote="q", source_page_start=1, source_page_end=1,
            qualifiers_json=qualifiers,
        )
        assert json.loads(fact.qualifiers_json) == ["consolidated", "audited"]

    def test_fact_all_value_types(self):
        """All ValueType enum members should be accepted."""
        for vt in ValueType:
            fact = FactSchema(
                id="f", document_id="d", chunk_id="c",
                subject="X", predicate="p", value_text="v",
                value_type=vt,
                source_quote="q", source_page_start=1, source_page_end=1,
            )
            assert fact.value_type == vt

    def test_fact_serialization_roundtrip(self):
        """Serialize to dict and back."""
        fact = FactSchema(
            id="f-1", document_id="d", chunk_id="c",
            subject="Co", predicate="metric",
            value_text="100", value_type=ValueType.NUMBER,
            numeric_value=100.0,
            source_quote="metric was 100", source_page_start=1, source_page_end=1,
        )
        d = fact.model_dump()
        restored = FactSchema(**d)
        assert restored.numeric_value == 100.0
        assert restored.value_type == ValueType.NUMBER


# ── Entity ─────────────────────────────────────────────────────────


class TestEntitySchema:
    def test_valid_entity(self):
        e = EntitySchema(
            id="e-1", canonical_name="Acme Corporation",
            entity_type=EntityType.COMPANY, confidence=0.95,
        )
        assert e.entity_type == EntityType.COMPANY


# ── Entity Alias ───────────────────────────────────────────────────


class TestEntityAliasSchema:
    def test_valid_alias(self):
        a = EntityAliasSchema(
            id="a-1", entity_id="e-1", alias="Acme Corp.", confidence=0.9,
        )
        assert a.alias == "Acme Corp."


# ── Fact Embedding ─────────────────────────────────────────────────


class TestFactEmbeddingSchema:
    def test_valid_embedding(self):
        e = FactEmbeddingSchema(
            id="emb-1", fact_id="f-1", model="text-embedding-3-small",
            dimensions=1536, content_hash="hash123",
        )
        assert e.dimensions == 1536


# ── Candidate Pair ─────────────────────────────────────────────────


class TestCandidatePairSchema:
    def test_valid_candidate(self):
        cp = CandidatePairSchema(
            id="cp-1", fact_a_id="f-1", fact_b_id="f-2",
            entity_similarity=0.95, predicate_similarity=0.91,
            semantic_similarity=0.88, candidate_score=0.91,
            reason_json=json.dumps(["same entity", "similar predicate"]),
        )
        assert cp.status == CandidateStatus.PENDING
        reasons = json.loads(cp.reason_json)
        assert "same entity" in reasons


# ── Relationship ───────────────────────────────────────────────────


class TestRelationshipSchema:
    def test_valid_relationship(self):
        rel = RelationshipSchema(
            id="r-1", fact_a_id="f-1", fact_b_id="f-2",
            relationship_type=RelationshipType.RECONCILES,
            confidence=0.94,
            primary_dimension=PrimaryDimension.TIME,
            context_comparison_json=json.dumps({
                "period_a": "FY2025",
                "period_b": "Q4 FY2025",
                "period_match": False,
            }),
            explanation="Different periods explain the value difference.",
            evidence_fact_a="Revenue for FY2025 was $12.5B.",
            evidence_fact_b="Q4 revenue reached $3.2B.",
            reasoning_version="v1",
        )
        assert rel.relationship_type == RelationshipType.RECONCILES
        assert rel.primary_dimension == PrimaryDimension.TIME

    def test_all_relationship_types(self):
        for rt in RelationshipType:
            rel = RelationshipSchema(
                id="r", fact_a_id="a", fact_b_id="b",
                relationship_type=rt, explanation="test",
            )
            assert rel.relationship_type == rt

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            RelationshipSchema(
                id="r", fact_a_id="a", fact_b_id="b",
                relationship_type=RelationshipType.UNCERTAIN,
                confidence=-0.1, explanation="test",
            )


# ── Job ────────────────────────────────────────────────────────────


class TestJobSchema:
    def test_valid_job(self):
        job = JobSchema(
            id="j-1", job_type=JobType.FULL,
            document_ids_json=json.dumps(["doc1", "doc2"]),
        )
        assert job.status == JobStatus.QUEUED
        assert job.progress == 0.0

    def test_all_job_types(self):
        for jt in JobType:
            job = JobSchema(id="j", job_type=jt)
            assert job.job_type == jt


# ── LLM Cache ──────────────────────────────────────────────────────


class TestLLMCacheSchema:
    def test_valid_cache_entry(self):
        entry = LLMCacheSchema(
            id="lc-1", operation="extraction", model="gpt-4o",
            prompt_version="v3", input_hash="abcdef",
            response_json='{"facts": []}',
        )
        assert entry.operation == "extraction"
        parsed = json.loads(entry.response_json)
        assert "facts" in parsed


# ── Health ─────────────────────────────────────────────────────────


class TestHealthResponse:
    def test_defaults(self):
        h = HealthResponse()
        assert h.status == "ok"
        assert h.version == "0.1.0"
