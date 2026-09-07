"""Header/footer detection and removal.

Conservatively detects repeated text across pages and removes it from
cleaned text. Never discards the raw page text.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)

# How many leading/trailing lines to consider as potential headers/footers
SCAN_LINES = 3

# Minimum fraction of pages a line must appear on to be considered a header/footer
MIN_OCCURRENCE_RATIO = 0.4

# Minimum number of pages needed before we attempt detection
MIN_PAGES_FOR_DETECTION = 3


class HeaderFooterDetector:
    """Detects and removes repeated headers and footers across pages.

    Strategy:
    - Look at the first/last N lines of each page.
    - Normalize whitespace and strip page numbers.
    - Lines appearing on >= 40% of pages are likely headers/footers.
    - Conservative: only remove lines that are clearly boilerplate.
    """

    def __init__(
        self,
        scan_lines: int = SCAN_LINES,
        min_ratio: float = MIN_OCCURRENCE_RATIO,
        min_pages: int = MIN_PAGES_FOR_DETECTION,
    ):
        self.scan_lines = scan_lines
        self.min_ratio = min_ratio
        self.min_pages = min_pages

    @staticmethod
    def _normalize_for_comparison(line: str) -> str:
        """Normalize a line for comparison: strip whitespace, remove page numbers."""
        line = line.strip()
        # Remove standalone numbers (likely page numbers)
        line = re.sub(r"^\d+$", "", line)
        # Remove leading/trailing page number patterns like "Page 12" or "- 12 -"
        line = re.sub(r"^(page\s+)?\d+\s*$", "", line, flags=re.IGNORECASE)
        line = re.sub(r"^-\s*\d+\s*-$", "", line)
        # Collapse whitespace
        line = re.sub(r"\s+", " ", line).strip()
        return line

    def detect(self, page_texts: list[str]) -> tuple[set[str], set[str]]:
        """Detect repeated header and footer lines.

        Args:
            page_texts: List of raw text strings, one per page.

        Returns:
            (header_patterns, footer_patterns): Sets of normalized line patterns
            that appear to be repeated headers/footers.
        """
        if len(page_texts) < self.min_pages:
            return set(), set()

        header_counter: Counter[str] = Counter()
        footer_counter: Counter[str] = Counter()

        for text in page_texts:
            lines = text.split("\n")
            # Count potential header lines
            for line in lines[: self.scan_lines]:
                norm = self._normalize_for_comparison(line)
                if norm and len(norm) > 2:  # skip very short/empty
                    header_counter[norm] += 1
            # Count potential footer lines
            for line in lines[-self.scan_lines :]:
                norm = self._normalize_for_comparison(line)
                if norm and len(norm) > 2:
                    footer_counter[norm] += 1

        threshold = len(page_texts) * self.min_ratio

        headers = {pat for pat, count in header_counter.items() if count >= threshold}
        footers = {pat for pat, count in footer_counter.items() if count >= threshold}

        if headers:
            logger.info("Detected %d header patterns", len(headers))
        if footers:
            logger.info("Detected %d footer patterns", len(footers))

        return headers, footers

    def clean_page(
        self, text: str, header_patterns: set[str], footer_patterns: set[str]
    ) -> str:
        """Remove detected header/footer lines from a page's text.

        Only removes lines at the top/bottom of the page that match patterns.
        Interior text is never modified.

        Args:
            text: The page's raw text.
            header_patterns: Set of normalized patterns to remove from top.
            footer_patterns: Set of normalized patterns to remove from bottom.

        Returns:
            Cleaned text with headers/footers removed.
        """
        if not header_patterns and not footer_patterns:
            return text

        lines = text.split("\n")
        start = 0
        end = len(lines)

        # Remove header lines from the top
        for i in range(min(self.scan_lines, len(lines))):
            norm = self._normalize_for_comparison(lines[i])
            if norm in header_patterns or not norm:
                start = i + 1
            else:
                break

        # Remove footer lines from the bottom
        for i in range(len(lines) - 1, max(len(lines) - self.scan_lines - 1, start - 1), -1):
            norm = self._normalize_for_comparison(lines[i])
            if norm in footer_patterns or not norm:
                end = i
            else:
                break

        return "\n".join(lines[start:end]).strip()
