"""Structured LLM fact extraction services and models."""

from app.services.extraction.models import ExtractedFact, ExtractionResult, PromptVersion
from app.services.extraction.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_messages
from app.services.extraction.service import (
    BaseExtractionProvider,
    ExtractionService,
    MockExtractionProvider,
    OpenAIExtractionProvider,
)
from app.services.extraction.verifier import EvidenceVerifier, VerificationResult

__all__ = [
    "ExtractedFact",
    "ExtractionResult",
    "PromptVersion",
    "EXTRACTION_SYSTEM_PROMPT",
    "build_extraction_messages",
    "ExtractionService",
    "BaseExtractionProvider",
    "OpenAIExtractionProvider",
    "MockExtractionProvider",
    "EvidenceVerifier",
    "VerificationResult",
]
