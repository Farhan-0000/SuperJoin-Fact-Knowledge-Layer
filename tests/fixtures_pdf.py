"""Helper to generate fixture PDF documents for testing."""

from __future__ import annotations

from pathlib import Path
import fitz  # PyMuPDF


def create_sample_pdf(output_path: Path | None = None) -> bytes:
    """Create a 4-page test PDF document with:
    - Page 1: Repeated header & footer, Heading, and Paragraphs
    - Page 2: Repeated header & footer, Heading, and a drawn Table (3x3)
    - Page 3: Low-text / scanned-like page (< 20 chars)
    - Page 4: Repeated header & footer, Heading, and Paragraphs
    """
    doc = fitz.open()

    # ── Page 1: Heading, text, header, footer ───────────────────────
    page1 = doc.new_page(width=600, height=800)
    page1.insert_text(fitz.Point(50, 40), "CONFIDENTIAL - ACME CORP REPORT", fontsize=10)
    page1.insert_text(fitz.Point(50, 100), "1. Executive Summary", fontsize=18)
    page1.insert_text(
        fitz.Point(50, 140),
        "Acme Corporation achieved revenue of $120 million in FY2025.",
        fontsize=11,
    )
    page1.insert_text(
        fitz.Point(50, 170),
        "Operating margin improved to 22 percent across all product divisions.",
        fontsize=11,
    )
    page1.insert_text(fitz.Point(50, 760), "CONFIDENTIAL - INTERNAL USE ONLY", fontsize=9)

    # ── Page 2: Table with vector borders ───────────────────────────
    page2 = doc.new_page(width=600, height=800)
    page2.insert_text(fitz.Point(50, 40), "CONFIDENTIAL - ACME CORP REPORT", fontsize=10)
    page2.insert_text(fitz.Point(50, 90), "2. Regional Financials", fontsize=18)

    # Draw table border lines
    # Table bounds: x from 50 to 450, y from 130 to 250
    # 3 cols: 50..180, 180..310, 310..450
    # 3 rows: 130..170 (header), 170..210 (row 1), 210..250 (row 2)
    x_coords = [50.0, 180.0, 310.0, 450.0]
    y_coords = [130.0, 170.0, 210.0, 250.0]

    # Draw outer and grid lines
    shape = page2.new_shape()
    for y in y_coords:
        shape.draw_line(fitz.Point(x_coords[0], y), fitz.Point(x_coords[-1], y))
    for x in x_coords:
        shape.draw_line(fitz.Point(x, y_coords[0]), fitz.Point(x, y_coords[-1]))
    shape.finish(color=(0, 0, 0), width=1)
    shape.commit()

    # Insert table text
    # Row 0 (Headers)
    page2.insert_text(fitz.Point(60, 155), "Region", fontsize=11)
    page2.insert_text(fitz.Point(190, 155), "Revenue", fontsize=11)
    page2.insert_text(fitz.Point(320, 155), "Growth", fontsize=11)

    # Row 1
    page2.insert_text(fitz.Point(60, 195), "North America", fontsize=10)
    page2.insert_text(fitz.Point(190, 195), "$65M", fontsize=10)
    page2.insert_text(fitz.Point(320, 195), "+14%", fontsize=10)

    # Row 2
    page2.insert_text(fitz.Point(60, 235), "Europe", fontsize=10)
    page2.insert_text(fitz.Point(190, 235), "$45M", fontsize=10)
    page2.insert_text(fitz.Point(320, 235), "+8%", fontsize=10)

    page2.insert_text(fitz.Point(50, 760), "CONFIDENTIAL - INTERNAL USE ONLY", fontsize=9)

    # ── Page 3: Low-text / scanned-like page ─────────────────────────
    page3 = doc.new_page(width=600, height=800)
    # Minimal text, below MIN_CHARS_FOR_GOOD_TEXT (50)
    page3.insert_text(fitz.Point(50, 100), "Scan", fontsize=10)

    # ── Page 4: Content page with repeated header & footer ──────────
    page4 = doc.new_page(width=600, height=800)
    page4.insert_text(fitz.Point(50, 40), "CONFIDENTIAL - ACME CORP REPORT", fontsize=10)
    page4.insert_text(fitz.Point(50, 100), "3. Future Outlook", fontsize=18)
    page4.insert_text(
        fitz.Point(50, 140),
        "Continued investment in artificial intelligence and automation will drive 2026 expansion.",
        fontsize=11,
    )
    page4.insert_text(fitz.Point(50, 760), "CONFIDENTIAL - INTERNAL USE ONLY", fontsize=9)

    pdf_bytes = doc.tobytes()
    doc.close()

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)

    return pdf_bytes
