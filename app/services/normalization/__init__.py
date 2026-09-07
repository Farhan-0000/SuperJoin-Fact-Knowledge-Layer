"""Deterministic normalization, entity resolution, and deduplication services."""

from app.services.normalization.numeric import NumericNormalizationResult, normalize_numeric
from app.services.normalization.dates import DateNormalizationResult, normalize_date_period
from app.services.normalization.predicates import PredicateNormalizationResult, normalize_predicate
from app.services.normalization.entities import EntityResolver, ResolvedEntity
from app.services.normalization.deduplication import deduplicate_facts
from app.services.normalization.pipeline import NormalizationPipeline

__all__ = [
    "normalize_numeric",
    "NumericNormalizationResult",
    "normalize_date_period",
    "DateNormalizationResult",
    "normalize_predicate",
    "PredicateNormalizationResult",
    "EntityResolver",
    "ResolvedEntity",
    "deduplicate_facts",
    "NormalizationPipeline",
]
