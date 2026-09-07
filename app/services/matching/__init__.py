"""Matching workers — candidate retrieval and fact deduplication."""

from app.services.matching.candidates import (
    CandidateGenerator,
    check_entity_compatibility_and_similarity,
    check_predicate_similarity,
    check_scope_compatibility,
    check_temporal_compatibility,
    check_unit_compatibility,
)
from app.services.matching.embeddings import (
    BaseEmbeddingProvider,
    EmbeddingService,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_canonical_representation,
    cosine_similarity,
    deserialize_vector,
    serialize_vector,
)

__all__ = [
    "BaseEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "MockEmbeddingProvider",
    "EmbeddingService",
    "CandidateGenerator",
    "build_canonical_representation",
    "serialize_vector",
    "deserialize_vector",
    "cosine_similarity",
    "check_entity_compatibility_and_similarity",
    "check_predicate_similarity",
    "check_unit_compatibility",
    "check_temporal_compatibility",
    "check_scope_compatibility",
]
