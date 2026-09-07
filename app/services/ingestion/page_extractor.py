"""Page-level text extraction using PyMuPDF."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class ExtractedPage:
    """Raw data extracted from a single PDF page."""

    page_number: int  # 1-indexed
    width: float
    height: float
    raw_text: str
    block_count: int = 0


class PageExtractor:
    """Extracts raw page text and dimensions from a PyMuPDF document.

    Page numbers are 1-indexed (PDF page index + 1).
    """

    def extract_all(self, doc: fitz.Document) -> list[ExtractedPage]:
        """Extract text and metadata from every page.

        Args:
            doc: An open PyMuPDF Document.

        Returns:
            List of ExtractedPage objects, one per page.
        """
        pages: list[ExtractedPage] = []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            raw_text = page.get_text("text", sort=True)

            pages.append(
                ExtractedPage(
                    page_number=page_idx + 1,  # 1-indexed
                    width=round(page.rect.width, 2),
                    height=round(page.rect.height, 2),
                    raw_text=raw_text,
                )
            )

        logger.info("Extracted %d pages", len(pages))
        return pages
