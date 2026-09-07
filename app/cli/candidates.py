"""CLI command for semantic candidate pair generation.

Usage:
    python -m app.cli.candidates [DOCUMENT_ID] [--cross-doc-only] [--threshold FLOAT] [--top-k INT]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from app.db.database import init_db
from app.services.matching.candidates import CandidateGenerator


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.candidates",
        description="Run semantic candidate fact pair generation pipeline.",
    )
    parser.add_argument(
        "document_id",
        nargs="?",
        default=None,
        help="Optional document ID to generate candidates for.",
    )
    parser.add_argument(
        "--cross-doc-only",
        action="store_true",
        help="Only evaluate cross-document fact pairs.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Minimum candidate score to retain (default from config: 0.60).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Max candidate pairs to retain per fact (default from config: 10).",
    )

    args = parser.parse_args(argv)

    init_db()

    generator = CandidateGenerator(
        min_score=args.threshold,
        top_k=args.top_k,
    )

    print(f"Generating candidate pairs (doc={args.document_id}, cross_doc_only={args.cross_doc_only})...")
    candidates = generator.generate_candidates(
        document_id=args.document_id,
        cross_document_only=args.cross_doc_only,
        min_score=args.threshold,
        top_k=args.top_k,
    )

    print(f"\nGenerated {len(candidates)} candidate pairs:")
    for idx, cp in enumerate(candidates, 1):
        reasons = json.loads(cp.reason_json) if cp.reason_json else []
        print(f"\n[{idx}] Score: {cp.candidate_score:.2f} | Status: {cp.status.value}")
        print(f"    Fact A: {cp.fact_a_id} <-> Fact B: {cp.fact_b_id}")
        print(f"    Cross-Doc: {not cp.same_document}")
        print(f"    Reasons: {reasons}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
