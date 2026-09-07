"""V1 Document management and batch upload routes."""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.db.database import get_connection
from app.models.schemas import (
    DocumentSchema,
    DocumentStatus,
    PageSchema,
    UploadDocumentsResponse,
    UploadedDocumentItem,
)
from app.services.ingestion.document_ingestor import DocumentIngestor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    response_model=UploadDocumentsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload multiple PDF documents",
)
async def upload_documents(
    files: list[UploadFile] = File(..., description="One or more PDF files to upload"),
) -> UploadDocumentsResponse:
    """Upload multiple PDF files.

    - Validates PDF format (magic bytes b'%PDF' and extension).
    - Computes SHA-256 before processing.
    - Repeated submission of an identical PDF reuses the existing record without re-running ingestion.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided in upload request",
        )

    ingestor = DocumentIngestor()
    uploaded_items: list[UploadedDocumentItem] = []
    conn = get_connection()

    try:
        for file in files:
            filename = file.filename or "unknown.pdf"

            if not filename.lower().endswith(".pdf"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File '{filename}' is not a PDF. Only PDF files are supported.",
                )

            content = await file.read()

            if not content.startswith(b"%PDF"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File '{filename}' lacks a valid PDF header signature.",
                )

            # Compute SHA-256
            file_hash = hashlib.sha256(content).hexdigest()

            # Check if document already exists
            existing = conn.execute(
                "SELECT * FROM documents WHERE sha256 = ?", (file_hash,)
            ).fetchone()

            if existing:
                logger.info("Reusing existing document %s for sha256 %s", existing["id"], file_hash)
                uploaded_items.append(
                    UploadedDocumentItem(
                        id=existing["id"],
                        filename=existing["filename"],
                        original_filename=existing["original_filename"],
                        page_count=existing["page_count"],
                        status=existing["status"],
                        sha256=existing["sha256"],
                    )
                )
            else:
                # Ingest new document
                result = ingestor.ingest_from_bytes(content, filename)
                uploaded_items.append(
                    UploadedDocumentItem(
                        id=result.document_id,
                        filename=result.document_id + ".pdf",
                        original_filename=filename,
                        page_count=result.page_count,
                        status=DocumentStatus.UPLOADED.value,
                        sha256=file_hash,
                    )
                )

        return UploadDocumentsResponse(documents=uploaded_items)
    finally:
        conn.close()


@router.get("", response_model=list[DocumentSchema], summary="List documents")
def list_documents(
    limit: int = Query(50, ge=1, le=500, description="Maximum documents to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
) -> list[DocumentSchema]:
    """Retrieve all ingested documents with pagination and status filter."""
    conn = get_connection()
    try:
        query = "SELECT * FROM documents WHERE 1=1"
        params: list = []

        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [
            DocumentSchema(
                id=r["id"],
                filename=r["filename"],
                original_filename=r["original_filename"],
                sha256=r["sha256"],
                file_size=r["file_size"],
                page_count=r["page_count"],
                title=r["title"],
                document_type=r["document_type"],
                published_date=r["published_date"],
                reporting_period=r["reporting_period"],
                status=DocumentStatus(r["status"]),
                error_message=r["error_message"],
                metadata_json=r["metadata_json"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/{document_id}", response_model=DocumentSchema, summary="Get document details")
def get_document(document_id: str) -> DocumentSchema:
    """Retrieve detailed metadata for a single document by ID."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{document_id}' not found",
            )
        return DocumentSchema(
            id=row["id"],
            filename=row["filename"],
            original_filename=row["original_filename"],
            sha256=row["sha256"],
            file_size=row["file_size"],
            page_count=row["page_count"],
            title=row["title"],
            document_type=row["document_type"],
            published_date=row["published_date"],
            reporting_period=row["reporting_period"],
            status=DocumentStatus(row["status"]),
            error_message=row["error_message"],
            metadata_json=row["metadata_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    finally:
        conn.close()


@router.get("/{document_id}/pages", response_model=list[PageSchema], summary="Get document pages")
def get_document_pages(document_id: str) -> list[PageSchema]:
    """Retrieve all pages of a document with quality metrics and raw text."""
    conn = get_connection()
    try:
        # Check document exists
        doc = conn.execute("SELECT id FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{document_id}' not found",
            )

        rows = conn.execute(
            "SELECT * FROM pages WHERE document_id = ? ORDER BY page_number ASC",
            (document_id,),
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
