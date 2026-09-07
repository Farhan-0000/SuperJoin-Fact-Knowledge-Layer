"""Same-document fact deduplication with full evidence preservation.

CRITICAL RULES:
- Deduplication must preserve all source evidence locations.
- Do not merge facts merely because values are equal.
- Two identical values can refer to different periods, scopes, geographies, or metrics.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.models.schemas import FactSchema

logger = logging.getLogger(__name__)


def _dedup_key(fact: FactSchema) -> tuple:
    """Generate a composite grouping key for exact semantic fact equivalence.

    Facts are duplicates IF AND ONLY IF subject, predicate, normalized value,
    unit/currency, temporal context, scope, and geography are identical.
    """
    # 1. Subject / Entity
    subj = (fact.entity_id or fact.subject.strip().lower())

    # 2. Predicate
    pred = fact.predicate.strip().lower()

    # 3. Value
    if fact.normalized_numeric_value is not None:
        val = round(fact.normalized_numeric_value, 6)
    else:
        val = fact.value_text.strip().lower()

    unit = (fact.normalized_unit or fact.unit or fact.currency or "").strip().lower()

    # 4. Temporal Context
    # Different periods (e.g. FY2024 vs FY2025) will produce different keys!
    time_ctx = (fact.time_text or "").strip().lower()
    time_bounds = (fact.time_start or "", fact.time_end or "")

    # 5. Scope & Geography
    scope = (fact.scope or "").strip().lower()
    geo = (fact.geography or "").strip().lower()

    # 6. Qualifiers
    quals = tuple(sorted(json.loads(fact.qualifiers_json) if fact.qualifiers_json else []))

    return (subj, pred, val, unit, time_ctx, time_bounds, scope, geo, quals)


def deduplicate_facts(facts: list[FactSchema]) -> list[FactSchema]:
    """Deduplicate facts from the same document while preserving all evidence locations.

    Args:
        facts: List of FactSchema records from a document.

    Returns:
        List of deduplicated FactSchema records with merged evidence.
    """
    if not facts:
        return []

    groups: dict[tuple, list[FactSchema]] = {}
    for f in facts:
        key = _dedup_key(f)
        groups.setdefault(key, []).append(f)

    deduped_facts: list[FactSchema] = []
    for key, cluster in groups.items():
        if len(cluster) == 1:
            deduped_facts.append(cluster[0])
            continue

        # Merge cluster into a single fact preserving all evidence
        primary = cluster[0]

        # 1. Merge source block IDs (union of all blocks)
        all_block_ids: set[str] = set()
        for f in cluster:
            if f.source_block_ids_json:
                try:
                    bids = json.loads(f.source_block_ids_json)
                    all_block_ids.update(bids)
                except Exception:
                    pass

        # 2. Merge page ranges (min start, max end)
        start_page = min(f.source_page_start for f in cluster)
        end_page = max(f.source_page_end for f in cluster)

        # 3. Merge quotes
        all_quotes = list(dict.fromkeys(f.source_quote for f in cluster if f.source_quote))
        merged_quote = " | ".join(all_quotes)

        # 4. Merge notes
        all_notes: list[str] = []
        for f in cluster:
            if f.extraction_notes_json:
                try:
                    notes = json.loads(f.extraction_notes_json)
                    all_notes.extend(notes)
                except Exception:
                    pass
        all_notes.append(
            f"Deduplicated from {len(cluster)} identical claims across pages {start_page}–{end_page}."
        )

        merged_fact = FactSchema(
            id=primary.id,
            document_id=primary.document_id,
            chunk_id=primary.chunk_id,
            subject=primary.subject,
            subject_mention=primary.subject_mention,
            entity_id=primary.entity_id,
            predicate=primary.predicate,
            predicate_mention=primary.predicate_mention,
            value_text=primary.value_text,
            value_type=primary.value_type,
            numeric_value=primary.numeric_value,
            normalized_numeric_value=primary.normalized_numeric_value,
            unit=primary.unit,
            normalized_unit=primary.normalized_unit,
            currency=primary.currency,
            time_text=primary.time_text,
            time_start=primary.time_start,
            time_end=primary.time_end,
            time_granularity=primary.time_granularity,
            scope=primary.scope,
            geography=primary.geography,
            qualifiers_json=primary.qualifiers_json,
            source_quote=merged_quote,
            source_page_start=start_page,
            source_page_end=end_page,
            source_block_ids_json=json.dumps(sorted(list(all_block_ids))),
            extraction_confidence=max(f.extraction_confidence for f in cluster),
            validation_status=primary.validation_status,
            extraction_notes_json=json.dumps(all_notes),
            created_at=primary.created_at,
        )
        deduped_facts.append(merged_fact)

    logger.info(
        "Deduplication complete: %d input facts -> %d deduplicated facts (%d merged)",
        len(facts),
        len(deduped_facts),
        len(facts) - len(deduped_facts),
    )
    return deduped_facts
