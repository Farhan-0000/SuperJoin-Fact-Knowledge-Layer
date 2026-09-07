"""Table detection and extraction using PyMuPDF's find_tables()."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTable:
    """A table detected on a PDF page."""

    table_index: int
    headers: list[str]
    rows: list[list[str]]
    text: str  # Flattened text representation
    x0: float
    y0: float
    x1: float
    y1: float

    def to_metadata_json(self) -> str:
        """Serialize table structure to JSON for storage."""
        return json.dumps({
            "headers": self.headers,
            "rows": self.rows,
            "row_count": len(self.rows),
            "col_count": len(self.headers) if self.headers else (
                len(self.rows[0]) if self.rows else 0
            ),
        })


class TableExtractor:
    """Detects and extracts tables from a PyMuPDF page using find_tables().

    Produces both structured data (headers + rows) and a flattened text
    representation for downstream chunking.
    """

    def extract(self, page: fitz.Page) -> list[ExtractedTable]:
        """Extract all tables from a page.

        Args:
            page: A PyMuPDF Page object.

        Returns:
            List of ExtractedTable with structure and bounding boxes.
        """
        try:
            tables = page.find_tables()
        except Exception as exc:
            logger.warning(
                "Table detection failed on page %d: %s", page.number + 1, exc
            )
            return []

        extracted: list[ExtractedTable] = []
        for idx, table in enumerate(tables):
            try:
                # Extract structured data
                data = table.extract()
                if not data:
                    continue

                # First row as headers if it looks like header row
                headers = [str(cell or "") for cell in data[0]] if data else []
                rows = [
                    [str(cell or "") for cell in row]
                    for row in data[1:]
                ] if len(data) > 1 else []

                # Flatten to text representation
                text_parts: list[str] = []
                if headers:
                    text_parts.append(" | ".join(headers))
                    text_parts.append("-" * 40)
                for row in rows:
                    text_parts.append(" | ".join(row))
                text = "\n".join(text_parts)

                bbox = table.bbox
                extracted.append(
                    ExtractedTable(
                        table_index=idx,
                        headers=headers,
                        rows=rows,
                        text=text,
                        x0=round(bbox[0], 2),
                        y0=round(bbox[1], 2),
                        x1=round(bbox[2], 2),
                        y1=round(bbox[3], 2),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Table %d extraction failed on page %d: %s",
                    idx, page.number + 1, exc,
                )

        if extracted:
            logger.debug(
                "Extracted %d tables from page %d", len(extracted), page.number + 1
            )
        return extracted
