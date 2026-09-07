"""LLM providers for relationship reasoning."""

from __future__ import annotations

import abc
import logging
from typing import Optional

from app.config import get_settings
from app.models.schemas import PrimaryDimension, RelationshipType
from app.services.reasoning.models import LLMRelationshipClassification

logger = logging.getLogger(__name__)


class BaseRelationshipProvider(abc.ABC):
    """Abstract interface for LLM relationship reasoning."""

    @abc.abstractmethod
    def classify(
        self, messages: list[dict[str, str]], model: str
    ) -> LLMRelationshipClassification:
        """Invoke LLM and return structured LLMRelationshipClassification."""
        ...


class OpenAIRelationshipProvider(BaseRelationshipProvider):
    """Production provider using OpenAI Python SDK structured output."""

    def __init__(self, api_key: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.effective_api_key
        self.base_url = settings.resolved_base_url

    def classify(
        self, messages: list[dict[str, str]], model: str
    ) -> LLMRelationshipClassification:
        """Call OpenAI/Gemini chat completions with Pydantic structured output."""
        import time
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        is_gemini = get_settings().is_gemini
        max_retries = 3
        delay = 5.0 if is_gemini else 1.0

        from app.core.rate_limiting import extract_retry_delay

        for attempt in range(max_retries):
            try:
                if is_gemini:
                    time.sleep(4.5)  # ~13 RPM, under 15 RPM free-tier limit
                completion = client.beta.chat.completions.parse(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    response_format=LLMRelationshipClassification,
                )
                parsed = completion.choices[0].message.parsed
                if parsed is None:
                    raise ValueError("OpenAI returned empty structured output for relationship")
                return parsed
            except Exception as exc:
                err_str = str(exc)
                if (
                    "RateLimit" in type(exc).__name__
                    or "429" in err_str
                    or "RESOURCE_EXHAUSTED" in err_str
                ) and attempt < max_retries - 1:
                    wait_time = extract_retry_delay(exc, default=delay) if is_gemini else delay
                    logger.warning(
                        "Rate limit in relationship reasoning (attempt %d/%d). Backing off %.1fs: %s",
                        attempt + 1,
                        max_retries,
                        wait_time,
                        exc,
                    )
                    time.sleep(wait_time)
                    delay = min(wait_time * 1.5, 120.0)
                elif attempt < max_retries - 1:
                    logger.warning(
                        "Transient error in relationship reasoning (attempt %d/%d): %s. Retrying in 1s...",
                        attempt + 1,
                        max_retries,
                        exc,
                    )
                    time.sleep(1.0)
                else:
                    raise


class MockRelationshipProvider(BaseRelationshipProvider):
    """Deterministic offline relationship provider for testing and environments without an API key."""

    def classify(
        self, messages: list[dict[str, str]], model: str
    ) -> LLMRelationshipClassification:
        user_content = ""
        for m in messages:
            if m.get("role") == "user":
                user_content = m.get("content", "").lower()

        # Check for related predicate keywords (e.g. revenue vs sales)
        if "predicate / metric: revenue" in user_content and "predicate / metric: sales" in user_content:
            return LLMRelationshipClassification(
                relationship_type=RelationshipType.RECONCILES,
                confidence=0.90,
                primary_dimension=PrimaryDimension.DEFINITION,
                explanation=(
                    "The terms 'revenue' and 'sales' are related top-line metrics; "
                    "the slight difference reflects reporting definition nuances between total gross revenue and net sales."
                ),
                context_comparison={"definition_variance": "revenue_vs_sales"},
            )

        # Default fallback
        return LLMRelationshipClassification(
            relationship_type=RelationshipType.UNCERTAIN,
            confidence=0.60,
            primary_dimension=PrimaryDimension.OTHER,
            explanation="Contextual evidence is insufficient to decisively corroborate or contradict.",
            context_comparison={},
        )
