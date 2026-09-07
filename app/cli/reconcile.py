"""CLI command for hybrid relationship classification and fact reconciliation.

Usage:
    python -m app.cli.reconcile [DOCUMENT_ID] [--force]
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from app.db.database import init_db
from app.services.reasoning.engine import RelationshipEngine


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.reconcile",
        description="Evaluate relationships (corroboration, contradiction, reconciliation) for candidate fact pairs.",
    )
    parser.add_argument(
        "document_id",
        nargs="?",
        default=None,
        help="Optional document ID to evaluate candidates for.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-evaluate candidate pairs even if already evaluated.",
    )

    args = parser.parse_args(argv)

    init_db()

    engine = RelationshipEngine()

    print(f"Evaluating candidate relationships (doc={args.document_id}, force={args.force})...")
    relationships = engine.evaluate_candidates(
        document_id=args.document_id,
        force=args.force,
    )

    print(f"\nEvaluated {len(relationships)} relationships:")
    for idx, rel in enumerate(relationships, 1):
        print(f"\n[{idx}] {rel.relationship_type.value.upper()} (Confidence: {rel.confidence:.2f}, Primary Dimension: {rel.primary_dimension.value if rel.primary_dimension else 'none'})")
        print(f"    Fact A: {rel.fact_a_id} <-> Fact B: {rel.fact_b_id}")
        print(f"    Explanation: {rel.explanation}")
        if rel.evidence_fact_a:
            print(f"    Evidence A: \"{rel.evidence_fact_a}\"")
        if rel.evidence_fact_b:
            print(f"    Evidence B: \"{rel.evidence_fact_b}\"")

    return 0


if __name__ == "__main__":
    sys.exit(main())
