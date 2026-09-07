"""Data models for relationship reasoning and structured LLM output."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.schemas import PrimaryDimension, RelationshipType


class LLMRelationshipClassification(BaseModel):
    """Structured response from LLM relationship verifier."""

    relationship_type: RelationshipType = Field(
        description="One of corroborates, contradicts, reconciles, uncertain, unrelated"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=1.0,
        description="Confidence score in the classification (0.0 to 1.0)",
    )
    primary_dimension: PrimaryDimension = Field(
        default=PrimaryDimension.VALUE,
        description="The primary dimension responsible: value, time, scope, unit, entity, definition, geography, other",
    )
    explanation: str = Field(
        description="Short evidence-based explanation suitable for a user interface"
    )
    context_comparison: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured context comparison across relevant dimensions",
    )
