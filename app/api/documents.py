"""Document management routes: upload, list, retrieve pages & layout blocks."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.db.database import get_connection
from app.models.schemas import (
    BlockSchema,
    ChunkSchema,
    DocumentSchema,
    DocumentStatus,
    DocumentUploadResponse,
    FactSchema,
    PageSchema,
)
from app.services.ingestion.document_ingestor import DocumentIngestor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a PDF document",
)
async def upload_document(
    file: UploadFile = File(..., description="PDF document to ingest"),
    force: bool = Query(
        default=False,
        description="If True, reprocess the document even if a duplicate SHA-256 exists",
    ),
) -> DocumentUploadResponse:
    """Accepts a PDF file, computes SHA-256, checks for duplicates, extracts

    pages, layout blocks, and tables, and saves to storage.
    """
    filename = file.filename or "document.pdf"

    # Enforce PDF only
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only PDF files are accepted. Received '{filename}'.",
        )

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {exc}",
        )

    if not content.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{filename}' is not a valid PDF document (magic bytes missing).",
        )

    ingestor = DocumentIngestor()
    try:
        result = ingestor.ingest_from_bytes(content, original_filename=filename, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to ingest document %s: %s", filename, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document ingestion failed: {exc}",
        )

    if result.is_duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Duplicate document rejected. A document with this SHA-256 already exists.",
                "document_id": result.document_id,
                "sha256": result.sha256,
            },
        )

    if result.error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Document processing failed: {result.error}",
        )

    return DocumentUploadResponse(
        id=result.document_id,
        filename=result.filename,
        page_count=result.page_count,
        status=DocumentStatus.UPLOADED,
        message=f"Successfully ingested {result.page_count} pages, {result.block_count} blocks, and {result.table_count} tables.",
    )


@router.get("", response_model=list[DocumentSchema], summary="List all ingested documents")
def list_documents() -> list[DocumentSchema]:
    """Retrieve all ingested documents."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY created_at DESC"
        ).fetchall()
        return [DocumentSchema(**dict(row)) for row in rows]
    finally:
        conn.close()


@router.get("/{doc_id}", response_model=DocumentSchema, summary="Get document details")
def get_document(doc_id: str) -> DocumentSchema:
    """Retrieve details for a single document by ID."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return DocumentSchema(**dict(row))
    finally:
        conn.close()


@router.get("/{doc_id}/pages", response_model=list[PageSchema], summary="Get document pages")
def get_document_pages(doc_id: str) -> list[PageSchema]:
    """Retrieve all extracted pages for a document in order."""
    conn = get_connection()
    try:
        doc = conn.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        rows = conn.execute(
            "SELECT * FROM pages WHERE document_id = ? ORDER BY page_number ASC",
            (doc_id,),
        ).fetchall()
        return [
            PageSchema(
                id=r["id"],
                document_id=r["document_id"],
                page_number=r["page_number"],
                width=r["width"],
                height=r["height"],
                raw_text=r["raw_text"],
                cleaned_text=r["cleaned_text"],
                text_quality=r["text_quality"],
                is_scanned=bool(r["is_scanned"]),
                metadata_json=r["metadata_json"],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/{doc_id}/blocks", response_model=list[BlockSchema], summary="Get layout blocks")
def get_document_blocks(
    doc_id: str,
    page_number: Optional[int] = Query(None, description="Optional page number filter"),
) -> list[BlockSchema]:
    """Retrieve layout blocks (paragraphs, headings, tables) with coordinates."""
    conn = get_connection()
    try:
        doc = conn.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        if page_number is not None:
            rows = conn.execute(
                """SELECT b.* FROM blocks b
                   JOIN pages p ON b.page_id = p.id
                   WHERE p.document_id = ? AND p.page_number = ?
                   ORDER BY b.reading_order ASC""",
                (doc_id, page_number),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT b.* FROM blocks b
                   JOIN pages p ON b.page_id = p.id
                   WHERE p.document_id = ?
                   ORDER BY p.page_number ASC, b.reading_order ASC""",
                (doc_id,),
            ).fetchall()

        return [
            BlockSchema(
                id=r["id"],
                page_id=r["page_id"],
                block_index=r["block_index"],
                block_type=r["block_type"],
                text=r["text"],
                x0=r["x0"],
                y0=r["y0"],
                x1=r["x1"],
                y1=r["y1"],
                reading_order=r["reading_order"],
                content_hash=r["content_hash"],
                metadata_json=r["metadata_json"],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.post("/{doc_id}/chunk", response_model=list[ChunkSchema], summary="Generate layout-aware chunks")
def chunk_document(
    doc_id: str,
    force: bool = Query(default=False, description="Force regeneration of chunks"),
) -> list[ChunkSchema]:
    """Partition document into semantic, layout-aware chunks."""
    from app.services.ingestion.chunker import LayoutAwareChunker

    conn = get_connection()
    try:
        doc = conn.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    finally:
        conn.close()

    chunker = LayoutAwareChunker()
    return chunker.chunk_document(doc_id, force=force)


@router.get("/{doc_id}/chunks", response_model=list[ChunkSchema], summary="Get document chunks")
def get_document_chunks(doc_id: str) -> list[ChunkSchema]:
    """Retrieve all chunks for a document ordered by sequence index."""
    conn = get_connection()
    try:
        doc = conn.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        rows = conn.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY sequence_index ASC",
            (doc_id,),
        ).fetchall()
        from app.models.schemas import ChunkStatus

        return [
            ChunkSchema(
                id=r["id"],
                document_id=r["document_id"],
                sequence_index=r["sequence_index"],
                start_page=r["start_page"],
                end_page=r["end_page"],
                block_ids_json=r["block_ids_json"],
                heading_path_json=r["heading_path_json"],
                text=r["text"],
                token_count=r["token_count"],
                previous_chunk_id=r["previous_chunk_id"],
                next_chunk_id=r["next_chunk_id"],
                has_table=bool(r["has_table"]),
                has_low_quality_page=bool(r["has_low_quality_page"]),
                content_hash=r["content_hash"],
                extraction_status=ChunkStatus(r["extraction_status"]),
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.post("/{doc_id}/extract", response_model=list[FactSchema], summary="Extract facts from document")
async def extract_document_facts(
    doc_id: str,
    force: bool = Query(default=False, description="Force re-extraction of facts"),
) -> list[FactSchema]:
    """Trigger structured LLM fact extraction across all chunks of a document."""
    from app.services.extraction import ExtractionService

    conn = get_connection()
    try:
        doc = conn.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    finally:
        conn.close()

    service = ExtractionService()
    try:
        return await service.extract_document(doc_id, force=force)
    except Exception as exc:
        logger.error("Fact extraction failed for document %s: %s", doc_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fact extraction failed: {exc}",
        )


