"""CLI command for hybrid relationship classification and fact reconciliation.

Usage:
    python -m app.cli.reconcile <FACT_A_ID> <FACT_B_ID>
    python -m app.cli.reconcile [DOCUMENT_ID] [--force]
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from app.db.database import get_connection, init_db
from app.models.schemas import (
    EntitySchema,
    EntityType,
    FactSchema,
    ValidationStatus,
    ValueType,
)
from app.services.reasoning.engine import RelationshipEngine


def _load_fact(fact_id: str, db_path: Optional[str] = None) -> Optional[FactSchema]:
    """Retrieve an individual fact with complete provenance and evidence."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
        if not row:
            return None
        return FactSchema(
            id=row["id"],
            document_id=row["document_id"],
            chunk_id=row["chunk_id"],
            subject=row["subject"],
            subject_mention=row["subject_mention"],
            entity_id=row["entity_id"],
            predicate=row["predicate"],
            predicate_mention=row["predicate_mention"],
            value_text=row["value_text"],
            value_type=ValueType(row["value_type"]),
            numeric_value=row["numeric_value"],
            normalized_numeric_value=row["normalized_numeric_value"],
            unit=row["unit"],
            normalized_unit=row["normalized_unit"],
            currency=row["currency"],
            time_text=row["time_text"],
            time_start=row["time_start"],
            time_end=row["time_end"],
            time_granularity=row["time_granularity"],
            scope=row["scope"],
            geography=row["geography"],
            qualifiers_json=row["qualifiers_json"],
            source_quote=row["source_quote"],
            source_page_start=row["source_page_start"],
            source_page_end=row["source_page_end"],
            source_block_ids_json=row["source_block_ids_json"],
            extraction_confidence=row["extraction_confidence"],
            validation_status=ValidationStatus(row["validation_status"]),
            extraction_notes_json=row["extraction_notes_json"],
        )
    finally:
        conn.close()


def _load_entity(entity_id: Optional[str], db_path: Optional[str] = None) -> Optional[EntitySchema]:
    """Retrieve an individual entity by ID."""
    if not entity_id:
        return None
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
        if not row:
            return None
        return EntitySchema(
            id=row["id"],
            canonical_name=row["canonical_name"],
            entity_type=EntityType(row["entity_type"]),
            aliases_json=row["aliases_json"],
            cik=row["cik"],
            ticker=row["ticker"],
            isin=row["isin"],
            metadata_json=row["metadata_json"],
        )
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.reconcile",
        description="Evaluate relationships (corroboration, contradiction, reconciliation) for candidate fact pairs or specific fact pairs.",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Either two fact IDs (<FACT_A_ID> <FACT_B_ID>) to evaluate a specific pair, or an optional [DOCUMENT_ID] to evaluate candidates for.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-evaluate candidate pairs even if already evaluated.",
    )

    args = parser.parse_args(argv)

    init_db()
    engine = RelationshipEngine()

    # Case 1: Exactly two arguments provided -> evaluate specific fact pair
    if len(args.targets) == 2:
        fact_a_id, fact_b_id = args.targets[0], args.targets[1]
        print(f"Loading facts for direct evaluation: '{fact_a_id}' <-> '{fact_b_id}'...")
        fact_a = _load_fact(fact_a_id)
        if not fact_a:
            print(f"Error: Fact '{fact_a_id}' not found in database.", file=sys.stderr)
            return 1
        fact_b = _load_fact(fact_b_id)
        if not fact_b:
            print(f"Error: Fact '{fact_b_id}' not found in database.", file=sys.stderr)
            return 1

        entity_a = _load_entity(fact_a.entity_id)
        entity_b = _load_entity(fact_b.entity_id)

        rel = engine.evaluate_pair(fact_a, fact_b, entity_a, entity_b)
        print(f"\nEvaluated relationship:")
        print(f"[{rel.relationship_type.value.upper()}] (Confidence: {rel.confidence:.2f}, Primary Dimension: {rel.primary_dimension.value if rel.primary_dimension else 'none'})")
        print(f"    Fact A ({rel.fact_a_id}): \"{fact_a.value_text}\" ({fact_a.predicate})")
        print(f"    Fact B ({rel.fact_b_id}): \"{fact_b.value_text}\" ({fact_b.predicate})")
        print(f"    Explanation: {rel.explanation}")
        if rel.evidence_fact_a:
            print(f"    Evidence A: \"{rel.evidence_fact_a}\"")
        if rel.evidence_fact_b:
            print(f"    Evidence B: \"{rel.evidence_fact_b}\"")
        return 0

    # Case 2: 0 or 1 argument provided -> evaluate candidate pairs across document or database
    doc_id = args.targets[0] if len(args.targets) == 1 else None
    print(f"Evaluating candidate relationships (doc={doc_id}, force={args.force})...")
    relationships = engine.evaluate_candidates(
        document_id=doc_id,
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
