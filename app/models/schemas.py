"""Pydantic schemas for API request/response and internal data transfer.

All domain models follow the Design.md specification.
Facts are GENERIC: subject/predicate/value, never domain-specific fields.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class BlockType(str, Enum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    TABLE = "table"
    CAPTION = "caption"
    LIST = "list"
    HEADER = "header"
    FOOTER = "footer"
    UNKNOWN = "unknown"


class ValueType(str, Enum):
    NUMBER = "number"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    DATE = "date"
    DURATION = "duration"
    BOOLEAN = "boolean"
    TEXT = "text"
    QUANTITY = "quantity"
    RANGE = "range"


class TimeGranularity(str, Enum):
    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"
    HALF = "half"
    YEAR = "year"
    FISCAL_YEAR = "fiscal_year"
    UNKNOWN = "unknown"


class ValidationStatus(str, Enum):
    VALIDATED = "validated"
    WARNING = "warning"
    REJECTED = "rejected"


class ChunkStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EntityType(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    COMPANY = "company"
    LOCATION = "location"
    PRODUCT = "product"
    OTHER = "other"


class RelationshipType(str, Enum):
    CORROBORATES = "corroborates"
    CONTRADICTS = "contradicts"
    RECONCILES = "reconciles"
    UNCERTAIN = "uncertain"
    UNRELATED = "unrelated"


class PrimaryDimension(str, Enum):
    VALUE = "value"
    TIME = "time"
    SCOPE = "scope"
    UNIT = "unit"
    ENTITY = "entity"
    DEFINITION = "definition"
    GEOGRAPHY = "geography"
    OTHER = "other"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    EVALUATED = "evaluated"
    SKIPPED = "skipped"


class JobType(str, Enum):
    FULL = "full"
    EXTRACTION = "extraction"
    RELATIONSHIP = "relationship"
    REPROCESS = "reprocess"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Document ───────────────────────────────────────────────────────


class DocumentSchema(BaseModel):
    """A PDF document ingested into the system."""
    id: str
    filename: str
    original_filename: str
    sha256: str
    file_size: int
    page_count: int | None = None
    title: str | None = None
    document_type: str | None = None
    published_date: str | None = None
    reporting_period: str | None = None
    status: DocumentStatus = DocumentStatus.UPLOADED
    error_message: str | None = None
    metadata_json: str | None = None  # flexible JSON metadata
    created_at: str
    updated_at: str


class DocumentUploadResponse(BaseModel):
    id: str
    filename: str
    page_count: int | None = None
    status: DocumentStatus
    message: str


# ── Page ───────────────────────────────────────────────────────────


class PageSchema(BaseModel):
    """A single PDF page with raw and cleaned text."""
    id: str
    document_id: str
    page_number: int  # 1-indexed
    width: float | None = None
    height: float | None = None
    raw_text: str
    cleaned_text: str | None = None
    text_quality: float | None = None  # 0.0-1.0
    is_scanned: bool = False
    metadata_json: str | None = None


# ── Block ──────────────────────────────────────────────────────────


class BlockSchema(BaseModel):
    """A layout block extracted from a PDF page (paragraph, table, heading, etc.)."""
    id: str
    page_id: str
    block_index: int
    block_type: BlockType = BlockType.UNKNOWN
    text: str
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    reading_order: int | None = None
    content_hash: str | None = None
    metadata_json: str | None = None  # table headers/rows stored here for table blocks


# ── Chunk ──────────────────────────────────────────────────────────


class ChunkSchema(BaseModel):
    """A semantic/layout-aware text chunk sent to the extraction model."""
    id: str
    document_id: str
    sequence_index: int
    start_page: int
    end_page: int
    block_ids_json: str | None = None  # JSON array of block IDs
    heading_path_json: str | None = None  # JSON array of heading strings
    text: str
    token_count: int | None = None
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
    has_table: bool = False
    has_low_quality_page: bool = False
    content_hash: str | None = None
    extraction_status: ChunkStatus = ChunkStatus.PENDING


# ── Fact ───────────────────────────────────────────────────────────


class FactSchema(BaseModel):
    """A single factual claim extracted from a document.

    GENERIC: subject/predicate/value pattern.
    No domain-specific fields (revenue, CEO, etc.).
    """
    id: str
    document_id: str
    chunk_id: str

    # ── Meaning ────────────────────────────────────────────────
    subject: str
    subject_mention: str | None = None  # raw mention in source text
    entity_id: str | None = None  # FK to entities table

    predicate: str
    predicate_mention: str | None = None  # raw mention in source text

    # ── Value ──────────────────────────────────────────────────
    value_text: str
    value_type: ValueType = ValueType.TEXT

    numeric_value: float | None = None
    normalized_numeric_value: float | None = None

    unit: str | None = None
    normalized_unit: str | None = None

    currency: str | None = None

    # ── Temporal context ───────────────────────────────────────
    time_text: str | None = None
    time_start: str | None = None  # ISO date or partial
    time_end: str | None = None
    time_granularity: TimeGranularity | None = None

    # ── Scope ──────────────────────────────────────────────────
    scope: str | None = None
    geography: str | None = None
    qualifiers_json: str | None = None  # JSON array

    # ── Provenance ─────────────────────────────────────────────
    source_quote: str
    source_page_start: int
    source_page_end: int
    source_block_ids_json: str | None = None  # JSON array

    # ── Quality ────────────────────────────────────────────────
    extraction_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    validation_status: ValidationStatus = ValidationStatus.VALIDATED
    extraction_notes_json: str | None = None  # JSON array

    created_at: str | None = None


# ── Entity ─────────────────────────────────────────────────────────


class EntitySchema(BaseModel):
    """A resolved canonical entity (organization, person, location, etc.)."""
    id: str
    canonical_name: str
    entity_type: EntityType = EntityType.OTHER
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    metadata_json: str | None = None
    created_at: str | None = None


# ── Entity Alias ───────────────────────────────────────────────────


class EntityAliasSchema(BaseModel):
    """An alias for a canonical entity."""
    id: str
    entity_id: str
    alias: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    created_at: str | None = None


# ── Fact Embedding ─────────────────────────────────────────────────


class FactEmbeddingSchema(BaseModel):
    """An embedding vector for a fact, used for candidate retrieval."""
    id: str
    fact_id: str
    model: str
    dimensions: int
    vector_blob: bytes | None = None  # serialized numpy array
    content_hash: str
    created_at: str | None = None


# ── Candidate Pair ─────────────────────────────────────────────────


class CandidatePairSchema(BaseModel):
    """A pair of facts selected for relationship evaluation."""
    id: str
    fact_a_id: str
    fact_b_id: str
    same_document: bool = False

    entity_similarity: float | None = None
    predicate_similarity: float | None = None
    semantic_similarity: float | None = None

    unit_compatible: bool | None = None
    period_compatible: bool | None = None
    scope_compatible: bool | None = None

    candidate_score: float = 0.0
    reason_json: str | None = None  # JSON array of strings

    status: CandidateStatus = CandidateStatus.PENDING
    created_at: str | None = None


# ── Relationship ───────────────────────────────────────────────────


class RelationshipSchema(BaseModel):
    """A classified relationship between two facts with full evidence."""
    id: str
    fact_a_id: str
    fact_b_id: str

    relationship_type: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    primary_dimension: PrimaryDimension | None = None
    context_comparison_json: str | None = None  # JSON dict

    explanation: str

    evidence_fact_a: str | None = None  # source quote from fact A
    evidence_fact_b: str | None = None  # source quote from fact B

    reasoning_version: str | None = None

    created_at: str | None = None


# ── Job ────────────────────────────────────────────────────────────


class JobSchema(BaseModel):
    """A background processing job."""
    id: str
    job_type: JobType = JobType.FULL
    document_ids_json: str | None = None  # JSON array of document IDs
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0  # 0-100
    current_stage: str | None = None
    total_items: int = 0
    completed_items: int = 0
    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


# ── LLM Cache ──────────────────────────────────────────────────────


class LLMCacheSchema(BaseModel):
    """A cached LLM response keyed by operation + model + prompt version + input hash."""
    id: str
    operation: str  # "extraction" | "relationship" | etc.
    model: str
    prompt_version: str
    input_hash: str
    response_json: str  # full JSON response
    created_at: str | None = None


# ── Health ─────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    database: str = "connected"
    documents_count: int = 0
