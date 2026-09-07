"""Document ingestion orchestrator.

Coordinates the full PDF ingestion pipeline:
  SHA-256 → duplicate check → save file → extract pages →
  extract blocks → detect tables → analyze quality →
  detect headers/footers → clean text → persist to DB.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import fitz  # PyMuPDF

from app.config import get_settings
from app.db.database import get_connection
from app.services.ingestion.page_extractor import PageExtractor, ExtractedPage
from app.services.ingestion.block_extractor import BlockExtractor, ExtractedBlock
from app.services.ingestion.table_extractor import TableExtractor, ExtractedTable
from app.services.ingestion.page_quality import PageQualityAnalyzer, PageQualityResult
from app.services.ingestion.header_footer import HeaderFooterDetector
from app.services.ingestion.ocr import OCRFallbackService, BaseOCRProvider

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF"


def _uid() -> str:
    return str(uuid.uuid4())


def _sha256_file(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


def _validate_pdf_header(header: bytes, filename: str) -> None:
    """Ensure file starts with PDF signature."""
    if not filename.lower().endswith(".pdf"):
        raise ValueError(f"Invalid file type for '{filename}': only PDF files (.pdf) are accepted")
    if not header.startswith(PDF_MAGIC):
        raise ValueError(f"Invalid file format for '{filename}': file header does not match PDF specification")


@dataclass
class IngestionResult:
    """Result of document ingestion."""

    document_id: str
    filename: str
    original_filename: str
    sha256: str
    page_count: int
    block_count: int
    table_count: int
    low_quality_pages: int
    is_duplicate: bool = False
    error: Optional[str] = None


class DocumentIngestor:
    """Orchestrates the full PDF ingestion pipeline.

    Pipeline stages:
      1. PDF format validation (accept PDF only)
      2. SHA-256 hash calculation
      3. Duplicate detection (reject by hash unless force=True)
      4. Save original PDF to STORAGE_DIR
      5. Open with PyMuPDF and extract pages
      6. Extract text blocks with bounding boxes
      7. Detect tables using find_tables()
      8. Analyze page quality (low-text/scanned detection)
      9. Detect and remove repeated headers/footers conservatively
      10. Optional OCR fallback (never runs automatically on all pages)
      11. Persist everything to SQLite
    """

    def __init__(
        self,
        ocr_service: Optional[OCRFallbackService] = None,
        auto_ocr_scanned: bool = False,
    ):
        self.page_extractor = PageExtractor()
        self.block_extractor = BlockExtractor()
        self.table_extractor = TableExtractor()
        self.quality_analyzer = PageQualityAnalyzer()
        self.hf_detector = HeaderFooterDetector()
        self.ocr_service = ocr_service or OCRFallbackService()
        self.auto_ocr_scanned = auto_ocr_scanned

    def ingest_from_path(
        self, file_path: Path, original_filename: Optional[str] = None, force: bool = False
    ) -> IngestionResult:
        """Ingest a PDF from a file path on disk.

        Args:
            file_path: Path to the PDF file.
            original_filename: Original name provided by user (defaults to file_path.name).
            force: If True, reprocess even if duplicate hash exists.

        Returns:
            IngestionResult with document metadata.
        """
        orig_name = original_filename or file_path.name

        # ── 1. Accept PDF only ────────────────────────────────────
        with open(file_path, "rb") as f:
            header = f.read(8)
        _validate_pdf_header(header, orig_name)

        # ── 2. SHA-256 ─────────────────────────────────────────────
        file_hash = _sha256_file(file_path)
        file_size = file_path.stat().st_size

        # ── 3. Duplicate check ─────────────────────────────────────
        existing_id = self._find_by_hash(file_hash)
        if existing_id and not force:
            logger.info("Duplicate document rejected: %s (hash=%s, existing_id=%s)", orig_name, file_hash[:12], existing_id)
            return IngestionResult(
                document_id=existing_id,
                filename="",
                original_filename=orig_name,
                sha256=file_hash,
                page_count=0,
                block_count=0,
                table_count=0,
                low_quality_pages=0,
                is_duplicate=True,
            )

        if existing_id and force:
            logger.info("Reprocessing existing document %s (force=True)", existing_id)
            self._delete_document(existing_id)

        # ── 4. Save to storage ─────────────────────────────────────
        settings = get_settings()
        doc_id = existing_id if (existing_id and force) else _uid()
        storage_filename = f"{doc_id}.pdf"
        storage_path = settings.storage_path / storage_filename
        shutil.copy2(str(file_path), str(storage_path))
        logger.info("Saved PDF to %s", storage_path)

        # ── 5–11. Process the PDF ──────────────────────────────────
        try:
            return self._process_pdf(
                doc_id=doc_id,
                storage_path=storage_path,
                storage_filename=storage_filename,
                original_filename=orig_name,
                file_hash=file_hash,
                file_size=file_size,
            )
        except Exception as exc:
            logger.error("Ingestion failed for %s: %s", orig_name, exc)
            self._save_error_document(
                doc_id, storage_filename, orig_name, file_hash, file_size, str(exc)
            )
            return IngestionResult(
                document_id=doc_id,
                filename=storage_filename,
                original_filename=orig_name,
                sha256=file_hash,
                page_count=0,
                block_count=0,
                table_count=0,
                low_quality_pages=0,
                error=str(exc),
            )

    def ingest_from_bytes(
        self, data: bytes, original_filename: str, force: bool = False
    ) -> IngestionResult:
        """Ingest a PDF from in-memory bytes (e.g. from file upload).

        Args:
            data: Raw PDF bytes.
            original_filename: Original name provided by user.
            force: If True, reprocess even if duplicate hash exists.

        Returns:
            IngestionResult with document metadata.
        """
        # ── 1. Accept PDF only ────────────────────────────────────
        _validate_pdf_header(data[:8], original_filename)

        # ── 2. SHA-256 ─────────────────────────────────────────────
        file_hash = _sha256_bytes(data)
        file_size = len(data)

        # ── 3. Duplicate check ─────────────────────────────────────
        existing_id = self._find_by_hash(file_hash)
        if existing_id and not force:
            logger.info("Duplicate document rejected: %s (hash=%s, existing_id=%s)", original_filename, file_hash[:12], existing_id)
            return IngestionResult(
                document_id=existing_id,
                filename="",
                original_filename=original_filename,
                sha256=file_hash,
                page_count=0,
                block_count=0,
                table_count=0,
                low_quality_pages=0,
                is_duplicate=True,
            )

        if existing_id and force:
            logger.info("Reprocessing existing document %s (force=True)", existing_id)
            self._delete_document(existing_id)

        # ── 4. Save to storage ─────────────────────────────────────
        settings = get_settings()
        doc_id = existing_id if (existing_id and force) else _uid()
        storage_filename = f"{doc_id}.pdf"
        storage_path = settings.storage_path / storage_filename
        storage_path.write_bytes(data)

        # ── 5–11. Process the PDF ──────────────────────────────────
        try:
            return self._process_pdf(
                doc_id=doc_id,
                storage_path=storage_path,
                storage_filename=storage_filename,
                original_filename=original_filename,
                file_hash=file_hash,
                file_size=file_size,
            )
        except Exception as exc:
            logger.error("Ingestion failed for %s: %s", original_filename, exc)
            self._save_error_document(
                doc_id, storage_filename, original_filename, file_hash, file_size, str(exc)
            )
            return IngestionResult(
                document_id=doc_id,
                filename=storage_filename,
                original_filename=original_filename,
                sha256=file_hash,
                page_count=0,
                block_count=0,
                table_count=0,
                low_quality_pages=0,
                error=str(exc),
            )

    def _process_pdf(
        self,
        doc_id: str,
        storage_path: Path,
        storage_filename: str,
        original_filename: str,
        file_hash: str,
        file_size: int,
    ) -> IngestionResult:
        """Core processing pipeline for a saved PDF."""
        doc = fitz.open(str(storage_path))
        try:
            page_count = len(doc)
            logger.info(
                "Processing %s: %d pages, %.1f KB",
                original_filename, page_count, file_size / 1024,
            )

            # ── 5. Extract pages (raw text preserved, 1-indexed) ──
            pages = self.page_extractor.extract_all(doc)

            # ── 6–7. Extract blocks and tables per page ────────────
            all_blocks: dict[int, list[ExtractedBlock]] = {}  # page_number → blocks
            all_tables: dict[int, list[ExtractedTable]] = {}  # page_number → tables
            total_block_count = 0
            total_table_count = 0

            for page_idx in range(page_count):
                pymupdf_page = doc[page_idx]
                page_num = page_idx + 1

                blocks = self.block_extractor.extract(pymupdf_page)
                all_blocks[page_num] = blocks
                total_block_count += len(blocks)

                tables = self.table_extractor.extract(pymupdf_page)
                all_tables[page_num] = tables
                total_table_count += len(tables)

            # ── 8. Page quality analysis (low-text/scanned detection)
            quality_results: dict[int, PageQualityResult] = {}
            low_quality_count = 0
            for ep in pages:
                qr = self.quality_analyzer.analyze(ep.raw_text, ep.width, ep.height)
                quality_results[ep.page_number] = qr
                if qr.is_scanned:
                    low_quality_count += 1

            # ── 9. Header/footer detection & cleaning ──────────────
            raw_texts = [ep.raw_text for ep in pages]
            header_pats, footer_pats = self.hf_detector.detect(raw_texts)

            # Clean text for each page (conservative removal from top/bottom only)
            cleaned_texts: dict[int, str] = {}
            for ep in pages:
                cleaned = self.hf_detector.clean_page(ep.raw_text, header_pats, footer_pats)

                # ── 10. OCR Fallback (Optional, never automatic for all pages)
                # Only runs if explicitly enabled AND page is scanned/low-text
                if self.auto_ocr_scanned and quality_results[ep.page_number].is_scanned:
                    ocr_text = self.ocr_service.ocr_page(
                        doc[ep.page_number - 1],
                        quality=quality_results[ep.page_number],
                    )
                    if ocr_text and ocr_text.strip():
                        # Append or use OCR text without altering original raw_text
                        cleaned = f"{cleaned}\n[OCR fallback]:\n{ocr_text.strip()}".strip()

                cleaned_texts[ep.page_number] = cleaned

            # ── 11. Persist to SQLite ──────────────────────────────
            self._persist(
                doc_id=doc_id,
                storage_filename=storage_filename,
                original_filename=original_filename,
                file_hash=file_hash,
                file_size=file_size,
                page_count=page_count,
                pages=pages,
                all_blocks=all_blocks,
                all_tables=all_tables,
                quality_results=quality_results,
                cleaned_texts=cleaned_texts,
            )

            logger.info(
                "Ingestion complete: %s -> %d pages, %d blocks, %d tables, %d low-quality",
                original_filename, page_count, total_block_count,
                total_table_count, low_quality_count,
            )

            return IngestionResult(
                document_id=doc_id,
                filename=storage_filename,
                original_filename=original_filename,
                sha256=file_hash,
                page_count=page_count,
                block_count=total_block_count,
                table_count=total_table_count,
                low_quality_pages=low_quality_count,
            )
        finally:
            doc.close()

    def _persist(
        self,
        doc_id: str,
        storage_filename: str,
        original_filename: str,
        file_hash: str,
        file_size: int,
        page_count: int,
        pages: list[ExtractedPage],
        all_blocks: dict[int, list[ExtractedBlock]],
        all_tables: dict[int, list[ExtractedTable]],
        quality_results: dict[int, PageQualityResult],
        cleaned_texts: dict[int, str],
    ) -> None:
        """Persist all extracted data to the database in a single transaction."""
        conn = get_connection()
        try:
            # Document record
            conn.execute(
                """INSERT INTO documents
                   (id, filename, original_filename, sha256, file_size, page_count, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, storage_filename, original_filename, file_hash,
                 file_size, page_count, "uploaded"),
            )

            # Pages
            for ep in pages:
                qr = quality_results.get(ep.page_number)
                page_id = _uid()
                conn.execute(
                    """INSERT INTO pages
                       (id, document_id, page_number, width, height,
                        raw_text, cleaned_text, text_quality, is_scanned)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (page_id, doc_id, ep.page_number, ep.width, ep.height,
                     ep.raw_text, cleaned_texts.get(ep.page_number, ep.raw_text),
                     qr.text_quality if qr else None,
                     1 if (qr and qr.is_scanned) else 0),
                )

                # Blocks for this page
                page_blocks = all_blocks.get(ep.page_number, [])
                for block in page_blocks:
                    conn.execute(
                        """INSERT INTO blocks
                           (id, page_id, block_index, block_type, text,
                            x0, y0, x1, y1, reading_order, content_hash, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (_uid(), page_id, block.block_index, block.block_type,
                         block.text, block.x0, block.y0, block.x1, block.y1,
                         block.reading_order, block.content_hash, None),
                    )

                # Table blocks for this page
                page_tables = all_tables.get(ep.page_number, [])
                for table in page_tables:
                    conn.execute(
                        """INSERT INTO blocks
                           (id, page_id, block_index, block_type, text,
                            x0, y0, x1, y1, reading_order, content_hash, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (_uid(), page_id,
                         len(page_blocks) + table.table_index,
                         "table", table.text,
                         table.x0, table.y0, table.x1, table.y1,
                         1000 + table.table_index,  # tables indexed after text blocks
                         hashlib.sha256(table.text.encode()).hexdigest()[:16],
                         table.to_metadata_json()),
                    )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _find_by_hash(self, file_hash: str) -> Optional[str]:
        """Check if a document with this SHA-256 already exists.

        Returns:
            Document ID if found, None otherwise.
        """
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id FROM documents WHERE sha256 = ?", (file_hash,)
            ).fetchone()
            return row["id"] if row else None
        finally:
            conn.close()

    def _delete_document(self, doc_id: str) -> None:
        """Delete an existing document and cascade delete its pages/blocks."""
        conn = get_connection()
        try:
            # Foreign key cascade is enabled in get_connection()
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _save_error_document(
        self,
        doc_id: str,
        filename: str,
        original_filename: str,
        file_hash: str,
        file_size: int,
        error: str,
    ) -> None:
        """Save a document record with error status."""
        conn = get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO documents
                   (id, filename, original_filename, sha256, file_size, status, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, filename, original_filename, file_hash,
                 file_size, "error", error),
            )
            conn.commit()
        finally:
            conn.close()
