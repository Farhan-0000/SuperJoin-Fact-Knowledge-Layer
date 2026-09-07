"""Pydantic schemas for API request/response and internal data transfer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class RelationshipType(str, Enum):
    CORROBORATES = "corroborates"
    CONTRADICTS = "contradicts"
    CONTEXTUALIZES = "contextualizes"


# ── Document ───────────────────────────────────────────────────────


class DocumentUploadResponse(BaseModel):
    id: str
    filename: str
    status: DocumentStatus
    message: str


class DocumentSummary(BaseModel):
    id: str
    filename: str
    original_name: str
    size_bytes: int
    page_count: Optional[int] = None
    status: DocumentStatus
    error_message: Optional[str] = None
    created_at: str
    updated_at: str


# ── Chunk ──────────────────────────────────────────────────────────


class ChunkSchema(BaseModel):
    id: str
    document_id: str
    page_number: int
    chunk_index: int
    text: str
    char_offset: Optional[int] = None
    char_length: Optional[int] = None


# ── Fact ───────────────────────────────────────────────────────────


class FactSchema(BaseModel):
    id: str
    document_id: str
    chunk_id: str
    claim: str
    source_quote: str
    page_number: int
    category: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    normalized_value: Optional[str] = None
    raw_value: Optional[str] = None
    unit: Optional[str] = None
    time_reference: Optional[str] = None
    entity: Optional[str] = None
    extraction_model: Optional[str] = None
    created_at: str


# ── Fact Relationship ──────────────────────────────────────────────


class FactRelationshipSchema(BaseModel):
    id: str
    fact_id_a: str
    fact_id_b: str
    relationship: RelationshipType
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_model: Optional[str] = None
    created_at: str


# ── Extraction Failure ─────────────────────────────────────────────


class ExtractionFailureSchema(BaseModel):
    id: str
    document_id: str
    chunk_id: Optional[str] = None
    failure_type: str
    description: str
    raw_input: Optional[str] = None
    raw_output: Optional[str] = None
    handling: str
    created_at: str


# ── Health ─────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    database: str = "connected"
    documents_count: int = 0
