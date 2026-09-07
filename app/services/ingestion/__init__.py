"""Ingestion services — PDF text, layout blocks, tables, quality analysis, and chunking."""

from app.services.ingestion.page_extractor import ExtractedPage, PageExtractor
from app.services.ingestion.block_extractor import ExtractedBlock, BlockExtractor
from app.services.ingestion.table_extractor import ExtractedTable, TableExtractor
from app.services.ingestion.header_footer import HeaderFooterDetector
from app.services.ingestion.page_quality import PageQualityAnalyzer, PageQualityResult
from app.services.ingestion.ocr import BaseOCRProvider, NoOpOCRProvider, OCRFallbackService
from app.services.ingestion.document_ingestor import DocumentIngestor, IngestionResult
from app.services.ingestion.tokenizer import count_tokens
from app.services.ingestion.chunker import LayoutAwareChunker, BlockRecord

__all__ = [
    "DocumentIngestor",
    "IngestionResult",
    "PageExtractor",
    "ExtractedPage",
    "BlockExtractor",
    "ExtractedBlock",
    "TableExtractor",
    "ExtractedTable",
    "HeaderFooterDetector",
    "PageQualityAnalyzer",
    "PageQualityResult",
    "OCRFallbackService",
    "BaseOCRProvider",
    "NoOpOCRProvider",
    "count_tokens",
    "LayoutAwareChunker",
    "BlockRecord",
]
