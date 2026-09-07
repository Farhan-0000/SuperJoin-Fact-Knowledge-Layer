"""Block-level text extraction with bounding boxes and reading order."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class ExtractedBlock:
    """A layout block extracted from a PDF page."""

    block_index: int
    block_type: str  # paragraph, heading, table, image, unknown
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    reading_order: int
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash and self.text:
            self.content_hash = hashlib.sha256(self.text.encode()).hexdigest()[:16]


# Heuristic heading patterns
_HEADING_PATTERNS = [
    re.compile(r"^(?:chapter|section|part)\s+\d", re.IGNORECASE),
    re.compile(r"^\d+\.\s+[A-Z]"),
    re.compile(r"^[A-Z][A-Z\s]{4,}$"),  # ALL CAPS
    re.compile(r"^\d+\.\d+[\.\d]*\s+\S"),  # numbered sections like 1.2.3
]

# Maximum characters for a heading line
MAX_HEADING_CHARS = 200


class BlockExtractor:
    """Extracts text blocks with bounding boxes from a PyMuPDF page.

    Classifies blocks as paragraph, heading, or image based on heuristics.
    Table blocks are identified separately by TableExtractor.
    """

    def extract(self, page: fitz.Page) -> list[ExtractedBlock]:
        """Extract all text blocks from a page.

        Args:
            page: A PyMuPDF Page object.

        Returns:
            List of ExtractedBlock with bounding boxes and reading order.
        """
        # dict output gives blocks with bounding boxes
        blocks_raw = page.get_text("dict", sort=True)["blocks"]

        extracted: list[ExtractedBlock] = []
        for order_idx, block in enumerate(blocks_raw):
            block_type_num = block.get("type", 0)

            if block_type_num == 1:
                # Image block
                extracted.append(
                    ExtractedBlock(
                        block_index=len(extracted),
                        block_type="image",
                        text="[image]",
                        x0=round(block["bbox"][0], 2),
                        y0=round(block["bbox"][1], 2),
                        x1=round(block["bbox"][2], 2),
                        y1=round(block["bbox"][3], 2),
                        reading_order=order_idx,
                    )
                )
                continue

            # Text block — gather text from lines/spans
            text_parts: list[str] = []
            font_sizes: list[float] = []
            is_bold_count = 0
            total_spans = 0

            for line in block.get("lines", []):
                line_texts: list[str] = []
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    if span_text.strip():
                        line_texts.append(span_text)
                        font_sizes.append(span.get("size", 12.0))
                        total_spans += 1
                        flags = span.get("flags", 0)
                        if flags & 2 ** 4:  # bold flag
                            is_bold_count += 1
                if line_texts:
                    text_parts.append(" ".join(line_texts))

            text = "\n".join(text_parts).strip()
            if not text:
                continue

            # Classify block type using heuristics
            btype = self._classify_block(
                text, font_sizes, is_bold_count, total_spans, page
            )

            extracted.append(
                ExtractedBlock(
                    block_index=len(extracted),
                    block_type=btype,
                    text=text,
                    x0=round(block["bbox"][0], 2),
                    y0=round(block["bbox"][1], 2),
                    x1=round(block["bbox"][2], 2),
                    y1=round(block["bbox"][3], 2),
                    reading_order=order_idx,
                )
            )

        return extracted

    def _classify_block(
        self,
        text: str,
        font_sizes: list[float],
        bold_count: int,
        total_spans: int,
        page: fitz.Page,
    ) -> str:
        """Classify a block as heading or paragraph using heuristics."""
        # Short text with large font or bold → heading
        lines = text.strip().split("\n")
        is_short = len(text) < MAX_HEADING_CHARS and len(lines) <= 3

        if is_short and font_sizes:
            avg_size = sum(font_sizes) / len(font_sizes)

            # If predominantly bold
            if total_spans > 0 and bold_count / total_spans > 0.5:
                return "heading"

            # If font size is notably larger than typical body text (12pt)
            if avg_size >= 14.0:
                return "heading"

        # Check against heading regex patterns
        first_line = lines[0].strip()
        if is_short:
            for pat in _HEADING_PATTERNS:
                if pat.match(first_line):
                    return "heading"

        return "paragraph"
