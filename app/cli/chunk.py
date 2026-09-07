"""CLI command for layout-aware document chunking.

Usage:
    python -m app.cli.chunk DOCUMENT_ID [--force] [--min-tokens N] [--max-tokens N]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from app.db.database import get_connection, init_db
from app.services.ingestion.chunker import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MIN_TOKENS,
    DEFAULT_OVERLAP_TOKENS,
    LayoutAwareChunker,
)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.chunk",
        description="Run page-aware, layout-aware chunking on an ingested PDF document.",
    )
    parser.add_argument(
        "document_id",
        help="ID of the document in the database to chunk.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-chunking even if chunks already exist for this document.",
    )
    parser.add_argument(
        "--min-tokens",
        type=int,
        default=DEFAULT_MIN_TOKENS,
        help=f"Target minimum tokens per chunk (default: {DEFAULT_MIN_TOKENS}).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Target maximum tokens per chunk (default: {DEFAULT_MAX_TOKENS}).",
    )
    parser.add_argument(
        "--overlap-tokens",
        type=int,
        default=DEFAULT_OVERLAP_TOKENS,
        help=f"Contextual overlap tokens between chunks (default: {DEFAULT_OVERLAP_TOKENS}).",
    )

    args = parser.parse_args(argv)

    init_db()

    conn = get_connection()
    try:
        doc = conn.execute(
            "SELECT id, original_filename, page_count FROM documents WHERE id = ?",
            (args.document_id,),
        ).fetchone()
    finally:
        conn.close()

    if not doc:
        print(f"Error: Document with ID '{args.document_id}' not found in database.", file=sys.stderr)
        return 1

    print(f"\n=======================================================")
    print(f"Chunking Document: {doc['original_filename']} (ID: {args.document_id})")
    print(f"Total Pages: {doc['page_count']}")
    print(f"Settings: min={args.min_tokens}, max={args.max_tokens}, overlap={args.overlap_tokens}")
    print(f"=======================================================\n")

    chunker = LayoutAwareChunker(
        min_tokens=args.min_tokens,
        max_tokens=args.max_tokens,
        overlap_tokens=args.overlap_tokens,
    )

    chunks = chunker.chunk_document(args.document_id, force=args.force)

    if not chunks:
        print("Warning: No chunks were generated (document may have no text blocks).")
        return 0

    print(f"Generated {len(chunks)} chunk(s):\n")
    print(f"{'Idx':<4} {'Pages':<10} {'Tokens':<8} {'Blocks':<8} {'Table':<7} {'Headings':<35} {'Hash':<16}")
    print("-" * 92)

    for c in chunks:
        page_range = f"p.{c.start_page}" if c.start_page == c.end_page else f"p.{c.start_page}-{c.end_page}"
        block_ids = json.loads(c.block_ids_json) if c.block_ids_json else []
        heading_path = json.loads(c.heading_path_json) if c.heading_path_json else []
        heading_str = " > ".join(heading_path) if heading_path else "[none]"
        if len(heading_str) > 33:
            heading_str = heading_str[:30] + "..."

        table_str = "Yes" if c.has_table else "No"
        hash_str = c.content_hash[:12] if c.content_hash else ""

        print(
            f"{c.sequence_index:<4} {page_range:<10} {c.token_count:<8} {len(block_ids):<8} "
            f"{table_str:<7} {heading_str:<35} {hash_str:<16}"
        )

    print("\nChunk linking summary:")
    for c in chunks:
        prev_str = c.previous_chunk_id[:8] if c.previous_chunk_id else "None"
        next_str = c.next_chunk_id[:8] if c.next_chunk_id else "None"
        print(f"  Chunk {c.sequence_index} ({c.id[:8]}): prev={prev_str}, next={next_str}")

    print("\nChunking completed successfully.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
