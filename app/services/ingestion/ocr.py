"""OCR fallback abstraction.

Provides pluggable OCR capabilities for scanned or low-text pages.
By design, does NOT automatically OCR every page — it only activates
on pages identified as low-quality/scanned when explicitly requested.
"""

from __future__ import annotations

import abc
import logging
from typing import Optional

import fitz  # PyMuPDF

from app.services.ingestion.page_quality import PageQualityResult

logger = logging.getLogger(__name__)


class BaseOCRProvider(abc.ABC):
    """Abstract interface for OCR text extraction backends."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of the OCR provider."""
        ...

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Check if the OCR backend and its dependencies are available."""
        ...

    @abc.abstractmethod
    def extract_text(self, page: fitz.Page) -> str:
        """Extract text from a PyMuPDF Page using OCR.

        Args:
            page: PyMuPDF Page object.

        Returns:
            Extracted text string.
        """
        ...


class PyMuPDFOCRProvider(BaseOCRProvider):
    """OCR provider using PyMuPDF's built-in Tesseract integration.

    Uses page.get_textpage_ocr() which requires Tesseract language data.
    """

    @property
    def name(self) -> str:
        return "pymupdf_ocr"

    def is_available(self) -> bool:
        """Check if PyMuPDF OCR is supported in this environment."""
        try:
            # Check if fitz has OCR support compiled in
            return hasattr(fitz, "open") and hasattr(fitz.Page, "get_textpage_ocr")
        except Exception:
            return False

    def extract_text(self, page: fitz.Page) -> str:
        """Run OCR on the page via PyMuPDF."""
        try:
            tp = page.get_textpage_ocr(flags=fitz.TEXT_PRESERVE_WHITESPACE, language="eng")
            return page.get_text("text", textpage=tp)
        except Exception as exc:
            logger.warning("PyMuPDF OCR failed for page %d: %s", page.number + 1, exc)
            return ""


class TesseractOCRProvider(BaseOCRProvider):
    """OCR provider using pytesseract and PIL/Pillow."""

    @property
    def name(self) -> str:
        return "pytesseract"

    def is_available(self) -> bool:
        try:
            import pytesseract  # type: ignore[import-not-found]
            return True
        except ImportError:
            return False

    def extract_text(self, page: fitz.Page) -> str:
        try:
            import io
            from PIL import Image
            import pytesseract

            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
            return pytesseract.image_to_string(img)
        except Exception as exc:
            logger.warning("pytesseract OCR failed for page %d: %s", page.number + 1, exc)
            return ""


class NoOpOCRProvider(BaseOCRProvider):
    """Fallback provider when no OCR backend is installed or configured."""

    @property
    def name(self) -> str:
        return "noop"

    def is_available(self) -> bool:
        return True

    def extract_text(self, page: fitz.Page) -> str:
        logger.info("NoOpOCRProvider called for page %d (no-op)", page.number + 1)
        return ""


class OCRFallbackService:
    """Coordinates OCR fallback for scanned or low-quality pages.

    Architecture rules:
    - Never OCR every page automatically.
    - Only evaluate pages flagged as scanned/low-text by PageQualityAnalyzer.
    - Support plugging custom OCR providers.
    """

    def __init__(self, provider: Optional[BaseOCRProvider] = None):
        if provider is not None:
            self.provider = provider
        else:
            # Auto-detect available provider in order of preference
            pymupdf_p = PyMuPDFOCRProvider()
            tesseract_p = TesseractOCRProvider()
            if pymupdf_p.is_available():
                self.provider = pymupdf_p
            elif tesseract_p.is_available():
                self.provider = tesseract_p
            else:
                self.provider = NoOpOCRProvider()

        logger.info("OCRFallbackService initialized with provider: %s", self.provider.name)

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def is_available(self) -> bool:
        """Return True if an active OCR engine is available."""
        return self.provider.is_available() and not isinstance(self.provider, NoOpOCRProvider)

    def should_ocr(self, quality: PageQualityResult) -> bool:
        """Determine if a page warrants OCR fallback.

        Only pages detected as scanned/low-text will return True.
        """
        return quality.is_scanned

    def ocr_page(
        self,
        page: fitz.Page,
        quality: Optional[PageQualityResult] = None,
        force: bool = False,
    ) -> Optional[str]:
        """Perform OCR on a page only if quality criteria require it or force is True.

        Args:
            page: PyMuPDF Page object.
            quality: Pre-computed quality result (optional).
            force: If True, bypass should_ocr check.

        Returns:
            OCR text if performed, None if OCR was skipped.
        """
        if not force and quality is not None and not self.should_ocr(quality):
            return None

        logger.info("Executing OCR fallback on page %d using %s", page.number + 1, self.provider.name)
        return self.provider.extract_text(page)
