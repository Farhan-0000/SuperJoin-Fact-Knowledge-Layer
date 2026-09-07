"""Page quality analysis — detect low-text and scanned pages."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Thresholds
MIN_CHARS_FOR_GOOD_TEXT = 50
LOW_TEXT_RATIO_THRESHOLD = 0.0004  # ~200 chars on a standard 500,000 sq point page


class PageQualityResult:
    """Result of page quality analysis."""

    __slots__ = ("text_length", "page_area", "char_density", "is_scanned", "text_quality")

    def __init__(
        self,
        text_length: int,
        page_area: float,
        char_density: float,
        is_scanned: bool,
        text_quality: float,
    ):
        self.text_length = text_length
        self.page_area = page_area
        self.char_density = char_density
        self.is_scanned = is_scanned
        self.text_quality = text_quality


class PageQualityAnalyzer:
    """Analyzes page text quality and detects scanned/low-text pages.

    Does NOT automatically invoke OCR — it only flags pages that would
    benefit from OCR so a later stage can decide.
    """

    def __init__(
        self,
        min_chars: int = MIN_CHARS_FOR_GOOD_TEXT,
        low_density_threshold: float = LOW_TEXT_RATIO_THRESHOLD,
    ):
        self.min_chars = min_chars
        self.low_density_threshold = low_density_threshold

    def analyze(self, raw_text: str, page_width: float, page_height: float) -> PageQualityResult:
        """Assess text quality for a single page.

        Returns:
            PageQualityResult with is_scanned flag and quality score.
        """
        text_length = len(raw_text.strip())
        page_area = max(page_width * page_height, 1.0)  # avoid div-by-zero
        char_density = text_length / page_area

        # A page is considered scanned/image-only if it has almost no text
        is_scanned = text_length < self.min_chars

        # Quality score: 1.0 = good text, 0.0 = no text
        if text_length == 0:
            text_quality = 0.0
        elif is_scanned:
            text_quality = round(min(text_length / max(self.min_chars, 1), 0.5), 3)
        elif char_density < self.low_density_threshold:
            text_quality = round(0.5 + 0.5 * (char_density / self.low_density_threshold), 3)
        else:
            text_quality = 1.0

        return PageQualityResult(
            text_length=text_length,
            page_area=page_area,
            char_density=round(char_density, 6),
            is_scanned=is_scanned,
            text_quality=text_quality,
        )
