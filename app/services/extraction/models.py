"""Pydantic models for structured LLM fact extraction."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.models.schemas import ValueType


class PromptVersion(str, Enum):
    """Prompt versions for fact extraction."""

    V1 = "v1"


class ExtractedFact(BaseModel):
    """A single factual claim extracted from document text.

    Strictly separates explicit source wording from normalized interpretation.
    CRITICAL: Does NOT contain page numbers; page provenance is resolved by the application.
    """

    # ── Explicit Source Wording (What the text actually says) ──
    source_quote: str = Field(
        ...,
        description="Exact verbatim quote directly from the supplied chunk text supporting this fact.",
    )
    subject_mention: str = Field(
        ...,
        description="Exact words in the text referring to the subject / entity.",
    )
    predicate_mention: str = Field(
        ...,
        description="Exact words in the text referring to the metric, property, or relation.",
    )
    value_text: str = Field(
        ...,
        description="Exact words in the text representing the value (e.g. '$120 million', '22%').",
    )

    # ── Normalized Interpretation ──────────────────────────────
    subject: str = Field(
        ...,
        description="Normalized or canonical entity/subject name (e.g. 'Acme Corporation').",
    )
    predicate: str = Field(
        ...,
        description="Normalized metric, property, or relation name (e.g. 'revenue', 'operating_margin').",
    )
    value_type: ValueType = Field(
        default=ValueType.TEXT,
        description="Semantic data type of the value.",
    )
    numeric_value: Optional[float] = Field(
        default=None,
        description="Parsed numerical value if applicable (e.g. 120000000.0 or 0.22).",
    )
    unit: Optional[str] = Field(
        default=None,
        description="Unit of measurement if specified (e.g. 'USD', '%', 'employees', 'metric tons').",
    )
    currency: Optional[str] = Field(
        default=None,
        description="ISO currency code or symbol if applicable (e.g. 'USD', '$', 'EUR').",
    )
    time_text: Optional[str] = Field(
        default=None,
        description="Temporal context as expressed in text (e.g. 'FY2025', 'Q3 2024', 'as of Dec 31').",
    )
    scope: Optional[str] = Field(
        default=None,
        description="Scope or boundary of the claim (e.g. 'consolidated', 'North America division').",
    )
    geography: Optional[str] = Field(
        default=None,
        description="Geographic region if mentioned (e.g. 'Global', 'Europe', 'India').",
    )
    qualifiers: list[str] = Field(
        default_factory=list,
        description="Qualifying conditions or modifiers (e.g. ['non-GAAP', 'adjusted', 'constant currency']).",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=1.0,
        description="Extraction confidence score from 0.0 to 1.0.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional notes on ambiguities, caveats, or contextual nuances.",
    )


class ExtractionResult(BaseModel):
    """Structured output returned by the LLM for a single chunk."""

    facts: list[ExtractedFact] = Field(
        default_factory=list,
        description="List of extracted facts strictly grounded in the supplied text.",
    )
    extraction_notes: list[str] = Field(
        default_factory=list,
        description="General observations, summary notes, or ambiguities detected in the chunk.",
    )
