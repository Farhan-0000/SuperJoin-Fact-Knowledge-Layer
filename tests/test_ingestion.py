"""Comprehensive test suite for Phase 3 — PDF Ingestion and Layout Preservation."""

from __future__ import annotations

import io
from pathlib import Path

import fitz  # PyMuPDF
import pytest
from fastapi.testclient import TestClient

from app.db.database import get_connection, init_db
from app.services.ingestion.block_extractor import BlockExtractor
from app.services.ingestion.document_ingestor import DocumentIngestor, IngestionResult
from app.services.ingestion.header_footer import HeaderFooterDetector
from app.services.ingestion.ocr import (
    BaseOCRProvider,
    NoOpOCRProvider,
    OCRFallbackService,
)
from app.services.ingestion.page_extractor import PageExtractor
from app.services.ingestion.page_quality import PageQualityAnalyzer, PageQualityResult
from app.services.ingestion.table_extractor import TableExtractor
from tests.fixtures_pdf import create_sample_pdf


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Fixture returning raw PDF bytes with 4 pages."""
    return create_sample_pdf()


@pytest.fixture
def sample_pdf_path(tmp_path: Path) -> Path:
    """Fixture creating and returning a physical test PDF file."""
    path = tmp_path / "test_sample.pdf"
    create_sample_pdf(path)
    return path


# ── 1. Page Extractor Tests ──────────────────────────────────────────


def test_page_extractor_page_count_and_indexing(sample_pdf_bytes: bytes):
    """Verify that PageExtractor extracts every page and indexes pages starting at 1."""
    doc = fitz.open(stream=sample_pdf_bytes, filetype="pdf")
    extractor = PageExtractor()
    pages = extractor.extract_all(doc)

    assert len(pages) == 4
    for idx, page in enumerate(pages):
        assert page.page_number == idx + 1
        assert page.width > 0
        assert page.height > 0
        assert isinstance(page.raw_text, str)
    doc.close()


def test_page_extractor_raw_text_preserved(sample_pdf_bytes: bytes):
    """Verify that raw_text is completely preserved including headers and footers."""
    doc = fitz.open(stream=sample_pdf_bytes, filetype="pdf")
    extractor = PageExtractor()
    pages = extractor.extract_all(doc)

    page1 = pages[0]
    assert "CONFIDENTIAL - ACME CORP REPORT" in page1.raw_text
    assert "1. Executive Summary" in page1.raw_text
    assert "revenue of $120 million" in page1.raw_text
    assert "CONFIDENTIAL - INTERNAL USE ONLY" in page1.raw_text
    doc.close()


# ── 2. Block Extractor & Coordinate Tests ─────────────────────────────


def test_block_extractor_coordinates_and_reading_order(sample_pdf_bytes: bytes):
    """Verify that blocks have valid coordinates and monotonic reading order."""
    doc = fitz.open(stream=sample_pdf_bytes, filetype="pdf")
    page = doc[0]  # Page 1
    extractor = BlockExtractor()
    blocks = extractor.extract(page)

    assert len(blocks) >= 3

    for block in blocks:
        # Check coordinate bounds
        assert 0.0 <= block.x0 < block.x1 <= 600.0
        assert 0.0 <= block.y0 < block.y1 <= 800.0
        assert len(block.text.strip()) > 0
        assert block.content_hash != ""

    # Check reading order
    reading_orders = [b.reading_order for b in blocks]
    assert reading_orders == sorted(reading_orders)
    doc.close()


def test_block_extractor_detects_headings(sample_pdf_bytes: bytes):
    """Verify that headings are detected by font size / regex patterns."""
    doc = fitz.open(stream=sample_pdf_bytes, filetype="pdf")
    page = doc[0]
    extractor = BlockExtractor()
    blocks = extractor.extract(page)

    heading_blocks = [b for b in blocks if b.block_type == "heading"]
    assert len(heading_blocks) >= 1
    heading_texts = [b.text for b in heading_blocks]
    assert any("Executive Summary" in t for t in heading_texts)
    doc.close()


# ── 3. Table Extractor Tests ──────────────────────────────────────────


def test_table_extractor_structure_and_coordinates(sample_pdf_bytes: bytes):
    """Verify table detection, header extraction, rows, and bounding boxes."""
    doc = fitz.open(stream=sample_pdf_bytes, filetype="pdf")
    page2 = doc[1]  # Page 2 has the drawn table
    extractor = TableExtractor()
    tables = extractor.extract(page2)

    assert len(tables) >= 1
    table = tables[0]

    # Verify table bounding box coordinates
    assert 0 <= table.x0 < table.x1 <= 600
    assert 0 <= table.y0 < table.y1 <= 800

    # Verify extracted headers and rows
    assert "Region" in table.headers or any("Region" in h for h in table.headers)
    assert len(table.rows) >= 2
    # Verify flattened text includes table elements
    assert "North America" in table.text
    assert "Europe" in table.text

    # Verify JSON metadata serialization
    meta_json = table.to_metadata_json()
    assert "headers" in meta_json
    assert "rows" in meta_json
    assert "row_count" in meta_json
    doc.close()


# ── 4. Quality Analyzer & Low-Text Detection ──────────────────────────


def test_low_text_scanned_page_detection(sample_pdf_bytes: bytes):
    """Verify that low-text / scanned pages are accurately detected and flagged."""
    analyzer = PageQualityAnalyzer(min_chars=50)

    # Page 1 has abundant text (> 150 chars)
    doc = fitz.open(stream=sample_pdf_bytes, filetype="pdf")
    page1_text = doc[0].get_text("text")
    res1 = analyzer.analyze(page1_text, 600, 800)
    assert not res1.is_scanned
    assert res1.text_quality > 0.5
    assert res1.text_length > 50

    # Page 3 has minimal text ("Scan" = 4 chars)
    page3_text = doc[2].get_text("text")
    res3 = analyzer.analyze(page3_text, 600, 800)
    assert res3.is_scanned
    assert res3.text_length < 50
    assert res3.text_quality < 0.2

    # Completely blank text
    res_empty = analyzer.analyze("", 600, 800)
    assert res_empty.is_scanned
    assert res_empty.text_quality == 0.0
    doc.close()


# ── 5. Header / Footer Detection Tests ────────────────────────────────


def test_header_footer_detector_conservative_removal(sample_pdf_bytes: bytes):
    """Verify conservative detection and removal of repeated headers/footers."""
    doc = fitz.open(stream=sample_pdf_bytes, filetype="pdf")
    pages = [doc[i].get_text("text") for i in range(len(doc))]
    doc.close()

    detector = HeaderFooterDetector(min_ratio=0.4, min_pages=3)
    headers, footers = detector.detect(pages)

    # Both header and footer appear on pages 1, 2, and 4 (3 out of 4 = 75% >= 40%)
    assert any("CONFIDENTIAL - ACME CORP REPORT" in h for h in headers)
    assert any("CONFIDENTIAL - INTERNAL USE ONLY" in f for f in footers)

    # Clean Page 1
    cleaned = detector.clean_page(pages[0], headers, footers)
    assert "CONFIDENTIAL - ACME CORP REPORT" not in cleaned
    assert "CONFIDENTIAL - INTERNAL USE ONLY" not in cleaned
    # Core content must be preserved
    assert "1. Executive Summary" in cleaned
    assert "revenue of $120 million" in cleaned


# ── 6. OCR Fallback Abstraction Tests ─────────────────────────────────


def test_ocr_fallback_abstraction_behavior():
    """Verify OCR fallback abstraction behaves as expected and does not OCR every page."""
    analyzer = PageQualityAnalyzer(min_chars=50)

    class MockOCRProvider(BaseOCRProvider):
        def __init__(self):
            self.call_count = 0

        @property
        def name(self) -> str:
            return "mock_ocr"

        def is_available(self) -> bool:
            return True

        def extract_text(self, page: fitz.Page) -> str:
            self.call_count += 1
            return "OCR recovered text: Scanned table row."

    mock_provider = MockOCRProvider()
    ocr_service = OCRFallbackService(provider=mock_provider)

    assert ocr_service.is_available()
    assert ocr_service.provider_name == "mock_ocr"

    # Good text page: should_ocr must return False
    good_quality = analyzer.analyze("This is a page with plenty of text " * 10, 600, 800)
    assert not ocr_service.should_ocr(good_quality)

    # Low text page: should_ocr must return True
    low_quality = analyzer.analyze("Scan", 600, 800)
    assert ocr_service.should_ocr(low_quality)

    # Test doc
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # Call ocr_page on good page without force: must be skipped
    result_good = ocr_service.ocr_page(page, quality=good_quality, force=False)
    assert result_good is None
    assert mock_provider.call_count == 0  # Not called automatically!

    # Call ocr_page on scanned page: must execute
    result_scanned = ocr_service.ocr_page(page, quality=low_quality, force=False)
    assert result_scanned == "OCR recovered text: Scanned table row."
    assert mock_provider.call_count == 1

    doc.close()


def test_noop_ocr_provider():
    """Verify NoOpOCRProvider handles missing engines gracefully."""
    noop = NoOpOCRProvider()
    assert noop.is_available()
    assert noop.name == "noop"
    doc = fitz.open()
    page = doc.new_page()
    assert noop.extract_text(page) == ""
    doc.close()


# ── 7. DocumentIngestor Full Pipeline & Duplicate Detection ───────────


def test_document_ingestor_full_pipeline(sample_pdf_bytes: bytes):
    """Test full ingestion pipeline from bytes into database."""
    init_db()
    ingestor = DocumentIngestor()

    result = ingestor.ingest_from_bytes(sample_pdf_bytes, "annual_report_2025.pdf")

    assert not result.is_duplicate
    assert result.error is None
    assert result.page_count == 4
    assert result.block_count > 0
    assert result.table_count >= 1
    assert result.low_quality_pages == 1  # Page 3 is low-text

    # Verify DB records
    conn = get_connection()
    doc_row = conn.execute("SELECT * FROM documents WHERE id = ?", (result.document_id,)).fetchone()
    assert doc_row is not None
    assert doc_row["sha256"] == result.sha256
    assert doc_row["page_count"] == 4

    # Verify pages
    pages = conn.execute(
        "SELECT * FROM pages WHERE document_id = ? ORDER BY page_number ASC",
        (result.document_id,),
    ).fetchall()
    assert len(pages) == 4
    assert pages[0]["page_number"] == 1
    assert pages[2]["is_scanned"] == 1  # Page 3

    # Raw text preserved, cleaned text has header removed
    assert "CONFIDENTIAL - ACME CORP REPORT" in pages[0]["raw_text"]
    assert "CONFIDENTIAL - ACME CORP REPORT" not in pages[0]["cleaned_text"]

    # Verify blocks
    blocks = conn.execute(
        """SELECT b.* FROM blocks b
           JOIN pages p ON b.page_id = p.id
           WHERE p.document_id = ?""",
        (result.document_id,),
    ).fetchall()
    assert len(blocks) == result.block_count + result.table_count
    conn.close()


def test_document_ingestor_rejects_duplicate_by_hash(sample_pdf_bytes: bytes):
    """Verify duplicate PDF documents are rejected unless force=True."""
    init_db()
    ingestor = DocumentIngestor()

    # First ingestion succeeds
    res1 = ingestor.ingest_from_bytes(sample_pdf_bytes, "report.pdf")
    assert not res1.is_duplicate

    # Second ingestion with same content rejects duplicate
    res2 = ingestor.ingest_from_bytes(sample_pdf_bytes, "report_copy.pdf", force=False)
    assert res2.is_duplicate
    assert res2.document_id == res1.document_id

    # Third ingestion with force=True reprocesses successfully
    res3 = ingestor.ingest_from_bytes(sample_pdf_bytes, "report_copy.pdf", force=True)
    assert not res3.is_duplicate
    assert res3.page_count == 4


def test_document_ingestor_accepts_pdf_only(tmp_path: Path):
    """Verify non-PDF documents are rejected with descriptive ValueError."""
    ingestor = DocumentIngestor()

    # Invalid extension
    with pytest.raises(ValueError, match="only PDF files"):
        ingestor.ingest_from_bytes(b"%PDF-1.4\nfake", "document.txt")

    # Invalid header
    with pytest.raises(ValueError, match="file header does not match"):
        ingestor.ingest_from_bytes(b"This is not a PDF file", "document.pdf")

    # From path with invalid file
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("plain text")
    with pytest.raises(ValueError, match="only PDF files"):
        ingestor.ingest_from_path(bad_file)


# ── 8. API Endpoint Integration Tests ─────────────────────────────────


def test_api_upload_pdf(client: TestClient, sample_pdf_bytes: bytes):
    """Test POST /api/documents/upload with valid PDF."""
    init_db()
    response = client.post(
        "/api/documents/upload",
        files={"file": ("company_report.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["page_count"] == 4
    assert data["status"] == "uploaded"
    assert "id" in data
    doc_id = data["id"]

    # Test GET /api/documents
    list_res = client.get("/api/documents")
    assert list_res.status_code == 200
    docs = list_res.json()
    assert any(d["id"] == doc_id for d in docs)

    # Test GET /api/documents/{id}
    detail_res = client.get(f"/api/documents/{doc_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["page_count"] == 4

    # Test GET /api/documents/{id}/pages
    pages_res = client.get(f"/api/documents/{doc_id}/pages")
    assert pages_res.status_code == 200
    pages = pages_res.json()
    assert len(pages) == 4
    assert pages[0]["page_number"] == 1
    assert pages[2]["is_scanned"] is True

    # Test GET /api/documents/{id}/blocks
    blocks_res = client.get(f"/api/documents/{doc_id}/blocks")
    assert blocks_res.status_code == 200
    blocks = blocks_res.json()
    assert len(blocks) > 0
    assert all("x0" in b and "y0" in b for b in blocks)


def test_api_upload_rejects_duplicates(client: TestClient, sample_pdf_bytes: bytes):
    """Test API rejects duplicate documents with HTTP 409 Conflict."""
    init_db()
    # First upload
    res1 = client.post(
        "/api/documents/upload",
        files={"file": ("original.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")},
    )
    assert res1.status_code == 201

    # Second upload with same PDF
    res2 = client.post(
        "/api/documents/upload",
        files={"file": ("duplicate.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")},
    )
    assert res2.status_code == 409
    assert "Duplicate document" in str(res2.json()["detail"])


def test_api_upload_rejects_non_pdf(client: TestClient):
    """Test API rejects non-PDF files with HTTP 400 Bad Request."""
    response = client.post(
        "/api/documents/upload",
        files={"file": ("data.csv", io.BytesIO(b"id,name\n1,Alice"), "text/csv")},
    )
    assert response.status_code == 400
    assert "Only PDF files are accepted" in response.json()["detail"]
