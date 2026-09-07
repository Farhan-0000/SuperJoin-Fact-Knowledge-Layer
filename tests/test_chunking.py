"""Test suite for Phase 4 — Layout-aware and Page-aware Chunking."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from app.cli.chunk import main as cli_chunk_main
from app.db.database import get_connection, init_db
from app.models.schemas import ChunkSchema
from app.services.ingestion.chunker import (
    BlockRecord,
    LayoutAwareChunker,
    _compute_chunk_content_hash,
    _compute_deterministic_chunk_id,
)
from app.services.ingestion.document_ingestor import DocumentIngestor
from tests.fixtures_pdf import create_sample_pdf


@pytest.fixture
def ingested_doc_id(tmp_path: Path) -> str:
    """Fixture that ingests a sample 4-page PDF and returns the document ID."""
    init_db()
    pdf_bytes = create_sample_pdf()
    ingestor = DocumentIngestor()
    result = ingestor.ingest_from_bytes(pdf_bytes, "sample_for_chunking.pdf")
    assert not result.is_duplicate
    assert result.page_count == 4
    return result.document_id


# ── 1. Chunk Ordering & Linkage ──────────────────────────────────────


def test_chunk_ordering_and_linkage(ingested_doc_id: str):
    """Verify that chunks have strictly ascending sequence_index (0, 1, 2...)

    and contiguous previous_chunk_id / next_chunk_id pointers.
    """
    # Use smaller max_tokens to force multiple chunks from sample PDF
    chunker = LayoutAwareChunker(min_tokens=20, max_tokens=60, overlap_tokens=15)
    chunks = chunker.chunk_document(ingested_doc_id, force=True)

    assert len(chunks) >= 2, "Should create multiple chunks with low token ceiling"

    for idx, chunk in enumerate(chunks):
        assert chunk.sequence_index == idx
        assert chunk.document_id == ingested_doc_id

        # First chunk
        if idx == 0:
            assert chunk.previous_chunk_id is None
            if len(chunks) > 1:
                assert chunk.next_chunk_id == chunks[1].id
        # Last chunk
        elif idx == len(chunks) - 1:
            assert chunk.previous_chunk_id == chunks[idx - 1].id
            assert chunk.next_chunk_id is None
        # Middle chunks
        else:
            assert chunk.previous_chunk_id == chunks[idx - 1].id
            assert chunk.next_chunk_id == chunks[idx + 1].id


# ── 2. Page Boundaries ────────────────────────────────────────────────


def test_chunk_page_boundaries(ingested_doc_id: str):
    """Verify start_page and end_page accurately reflect the blocks included in each chunk."""
    chunker = LayoutAwareChunker(min_tokens=20, max_tokens=80, overlap_tokens=10)
    chunks = chunker.chunk_document(ingested_doc_id, force=True)

    conn = get_connection()
    try:
        for chunk in chunks:
            assert 1 <= chunk.start_page <= chunk.end_page <= 4

            # Verify against database blocks
            block_ids = json.loads(chunk.block_ids_json)
            assert len(block_ids) > 0

            placeholders = ",".join("?" * len(block_ids))
            rows = conn.execute(
                f"""SELECT p.page_number FROM blocks b
                    JOIN pages p ON b.page_id = p.id
                    WHERE b.id IN ({placeholders})""",
                block_ids,
            ).fetchall()

            page_numbers = [r["page_number"] for r in rows]
            assert min(page_numbers) == chunk.start_page
            assert max(page_numbers) == chunk.end_page
    finally:
        conn.close()


# ── 3. Table Preservation ─────────────────────────────────────────────


def test_table_preservation_as_whole_unit():
    """Verify that table blocks are never fragmented across chunks and are kept intact."""
    doc_id = "test-doc-table"

    # Create mock blocks with a table between paragraphs
    blocks = [
        BlockRecord(
            id="b1",
            page_id="p1",
            page_number=1,
            block_index=0,
            block_type="heading",
            text="1. Financial Summary",
            reading_order=0,
        ),
        BlockRecord(
            id="b2",
            page_id="p1",
            page_number=1,
            block_index=1,
            block_type="paragraph",
            text="Here is the detailed performance data for our European and Asian operations.",
            reading_order=1,
        ),
        BlockRecord(
            id="b3",
            page_id="p1",
            page_number=1,
            block_index=2,
            block_type="table",
            text="Region | Revenue | Margin\n--------------------------------\nEurope | $45M | 18%\nAsia | $30M | 22%",
            reading_order=2,
        ),
        BlockRecord(
            id="b4",
            page_id="p1",
            page_number=1,
            block_index=3,
            block_type="paragraph",
            text="Following the regional results, global operations continued expansion.",
            reading_order=3,
        ),
    ]

    chunker = LayoutAwareChunker(min_tokens=15, max_tokens=40, overlap_tokens=0)
    chunks = chunker.create_chunks_from_blocks(document_id=doc_id, blocks=blocks)

    # Find chunk containing the table
    table_chunks = [c for c in chunks if c.has_table]
    assert len(table_chunks) >= 1

    tc = table_chunks[0]
    # The entire table text must appear unbroken in this chunk
    assert "Region | Revenue | Margin" in tc.text
    assert "Europe | $45M | 18%" in tc.text
    assert "Asia | $30M | 22%" in tc.text
    # Table block id must be in block_ids
    block_ids = json.loads(tc.block_ids_json)
    assert "b3" in block_ids


# ── 4. Contextual Overlap & Provenance Rule ───────────────────────────


def test_contextual_overlap_and_provenance_rule():
    """Verify contextual overlap exists between adjacent chunks and that every block cited in

    the chunk text is formally in the chunk's block_ids (Provenance Rule).
    """
    doc_id = "test-doc-overlap"

    blocks = [
        BlockRecord(
            id="b1",
            page_id="p1",
            page_number=1,
            block_index=0,
            block_type="heading",
            text="Section A: Foundations",
            reading_order=0,
        ),
        BlockRecord(
            id="b2",
            page_id="p1",
            page_number=1,
            block_index=1,
            block_type="paragraph",
            text="Alpha paragraph with important premise statements.",
            reading_order=1,
        ),
        BlockRecord(
            id="b3",
            page_id="p1",
            page_number=1,
            block_index=2,
            block_type="paragraph",
            text="Beta paragraph detailing experimental methodology and parameters.",
            reading_order=2,
        ),
        BlockRecord(
            id="b4",
            page_id="p2",
            page_number=2,
            block_index=3,
            block_type="heading",
            text="Section B: Results",
            reading_order=3,
        ),
        BlockRecord(
            id="b5",
            page_id="p2",
            page_number=2,
            block_index=4,
            block_type="paragraph",
            text="Gamma paragraph showing final metric calculations and outcomes.",
            reading_order=4,
        ),
    ]

    # Force boundary at Section B by setting min_tokens low
    chunker = LayoutAwareChunker(min_tokens=15, max_tokens=30, overlap_tokens=15)
    chunks = chunker.create_chunks_from_blocks(document_id=doc_id, blocks=blocks)

    assert len(chunks) == 2

    chunk_1, chunk_2 = chunks[0], chunks[1]

    # Chunk 2 should have contextual overlap from chunk 1
    assert "[Context from previous section]:" in chunk_2.text
    # Chunk 2 must include the overlap block text
    assert "Beta paragraph" in chunk_2.text

    # Provenance Rule check:
    # Any block present in chunk 2's text must be in chunk 2's block_ids
    c2_block_ids = json.loads(chunk_2.block_ids_json)
    assert "b3" in c2_block_ids, "Overlap block b3 must be in chunk 2 block_ids for provenance validation"
    assert "b4" in c2_block_ids
    assert "b5" in c2_block_ids


# ── 5. Deterministic Chunk Hashes ─────────────────────────────────────


def test_deterministic_chunk_hashes(ingested_doc_id: str):
    """Verify that chunk hashes and IDs are 100% deterministic across multiple runs."""
    chunker = LayoutAwareChunker(min_tokens=30, max_tokens=100, overlap_tokens=15)

    run_1 = chunker.chunk_document(ingested_doc_id, force=True)
    run_2 = chunker.chunk_document(ingested_doc_id, force=True)

    assert len(run_1) == len(run_2)

    for c1, c2 in zip(run_1, run_2):
        assert c1.id == c2.id
        assert c1.sequence_index == c2.sequence_index
        assert c1.content_hash == c2.content_hash
        assert c1.text == c2.text
        assert c1.token_count == c2.token_count
        assert c1.block_ids_json == c2.block_ids_json
        assert c1.heading_path_json == c2.heading_path_json
        assert c1.previous_chunk_id == c2.previous_chunk_id
        assert c1.next_chunk_id == c2.next_chunk_id


# ── 6. Heading Hierarchy Tracking ─────────────────────────────────────


def test_heading_path_hierarchy():
    """Verify that nested headings (e.g. 1. -> 1.1) update heading_path properly."""
    doc_id = "test-doc-headings"
    blocks = [
        BlockRecord(
            id="h1",
            page_id="p1",
            page_number=1,
            block_index=0,
            block_type="heading",
            text="1. Introduction",
            reading_order=0,
        ),
        BlockRecord(
            id="p1",
            page_id="p1",
            page_number=1,
            block_index=1,
            block_type="paragraph",
            text="Introduction narrative text.",
            reading_order=1,
        ),
        BlockRecord(
            id="h2",
            page_id="p1",
            page_number=1,
            block_index=2,
            block_type="heading",
            text="1.1 Overview",
            reading_order=2,
        ),
        BlockRecord(
            id="p2",
            page_id="p1",
            page_number=1,
            block_index=3,
            block_type="paragraph",
            text="Overview narrative text.",
            reading_order=3,
        ),
    ]

    chunker = LayoutAwareChunker(min_tokens=500, max_tokens=1000)
    chunks = chunker.create_chunks_from_blocks(document_id=doc_id, blocks=blocks)

    assert len(chunks) == 1
    hpath = json.loads(chunks[0].heading_path_json)
    assert len(hpath) >= 2
    assert "1. Introduction" in hpath[0]
    assert "1.1 Overview" in hpath[1]


# ── 7. CLI Command Tests ──────────────────────────────────────────────


def test_cli_chunk_command(ingested_doc_id: str, capsys: pytest.CaptureFixture):
    """Test running python -m app.cli.chunk DOCUMENT_ID via main()."""
    exit_code = cli_chunk_main([ingested_doc_id, "--force", "--min-tokens", "25", "--max-tokens", "80"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Chunking Document:" in captured.out
    assert "Generated" in captured.out
    assert "p." in captured.out
    assert "Chunk linking summary:" in captured.out


def test_cli_chunk_nonexistent_document(capsys: pytest.CaptureFixture):
    """Test CLI error handling when document does not exist."""
    exit_code = cli_chunk_main(["nonexistent-doc-uuid"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Error: Document with ID 'nonexistent-doc-uuid' not found" in captured.err


# ── 8. API Integration Tests for Chunks ────────────────────────────────


def test_api_chunk_endpoints(client: TestClient, sample_pdf_bytes: bytes):
    """Test POST /api/documents/{id}/chunk and GET /api/documents/{id}/chunks."""
    init_db()

    # 1. Upload PDF
    upload_res = client.post(
        "/api/documents/upload",
        files={"file": ("chunk_test.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # 2. Trigger chunk generation via API
    chunk_res = client.post(f"/api/documents/{doc_id}/chunk")
    assert chunk_res.status_code == 200
    chunks = chunk_res.json()
    assert len(chunks) >= 1
    assert chunks[0]["document_id"] == doc_id
    assert "content_hash" in chunks[0]

    # 3. Retrieve chunks via GET
    get_res = client.get(f"/api/documents/{doc_id}/chunks")
    assert get_res.status_code == 200
    get_chunks = get_res.json()
    assert len(get_chunks) == len(chunks)
    assert get_chunks[0]["sequence_index"] == 0
