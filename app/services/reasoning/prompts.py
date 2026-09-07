"""Prompts for LLM relationship reasoning."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.models.schemas import EntitySchema, FactSchema

RELATIONSHIP_SYSTEM_PROMPT = """You are a fact relationship verifier.
You are given two independently extracted facts and their source evidence.
Classify only one:
CORROBORATES
CONTRADICTS
RECONCILES
UNCERTAIN
UNRELATED

Do not call two facts contradictory merely because their values differ.
Require explicit compatibility for scope, geography, and currency before declaring CONTRADICTS.
If scope, geography, or currency differ or are asymmetric (e.g. one specifies a scope/geography and the other is unspecified), classify as RECONCILES or UNCERTAIN, not CONTRADICTS.
Examine:
entity identity;
predicate/metric equivalence;
numerical values;
units/currency;
reporting period;
scope;
geography;
definition;
qualifiers.

A relationship must be justified only using supplied fact data and source evidence.
Do not introduce facts not present in the inputs.
Return a short evidence-based explanation suitable for a user interface.
Also identify the primary dimension responsible for the relationship:
value, time, scope, unit, entity, definition, geography, other.

Do not expose hidden chain-of-thought. Return only a concise explanation of observable evidence and the decision."""


def format_fact_for_prompt(fact: FactSchema, entity: Optional[EntitySchema] = None) -> str:
    """Format a single fact and its provenance for relationship evaluation."""
    entity_name = entity.canonical_name if entity else fact.subject
    lines = [
        f"Subject / Entity: {entity_name} (mention: '{fact.subject_mention or fact.subject}')",
        f"Predicate / Metric: {fact.predicate} (mention: '{fact.predicate_mention or fact.predicate}')",
        f"Value Text: {fact.value_text}",
        f"Normalized Value: {fact.normalized_numeric_value if fact.normalized_numeric_value is not None else 'N/A'}",
        f"Unit / Currency: {fact.normalized_unit or fact.unit or 'N/A'} (Currency: {fact.currency or 'N/A'})",
        f"Reporting Period: {fact.time_text or 'N/A'} (Span: {fact.time_start or ''}..{fact.time_end or ''})",
        f"Scope: {fact.scope or 'unspecified'}",
        f"Geography: {fact.geography or 'unspecified'}",
    ]
    if fact.qualifiers_json:
        lines.append(f"Qualifiers: {fact.qualifiers_json}")
    lines.append(f"Source Evidence Quote: \"{fact.source_quote}\"")
    lines.append(f"Source Page(s): {fact.source_page_start}..{fact.source_page_end}")
    return "\n".join(lines)


def build_relationship_user_prompt(
    fact_a: FactSchema,
    fact_b: FactSchema,
    entity_a: Optional[EntitySchema] = None,
    entity_b: Optional[EntitySchema] = None,
    deterministic_comparison: Optional[dict[str, Any]] = None,
) -> str:
    """Build user message for relationship classification."""
    prompt = [
        "Please evaluate the relationship between Fact A and Fact B based ONLY on the supplied facts and evidence:\n",
        "--- FACT A ---",
        format_fact_for_prompt(fact_a, entity_a),
        "\n--- FACT B ---",
        format_fact_for_prompt(fact_b, entity_b),
    ]

    if deterministic_comparison:
        prompt.extend([
            "\n--- CONTEXT COMPARISON OBSERVATIONS ---",
            json.dumps(deterministic_comparison, indent=2),
        ])

    prompt.append(
        "\nClassify the relationship (CORROBORATES, CONTRADICTS, RECONCILES, UNCERTAIN, or UNRELATED) "
        "and provide a concise evidence-based explanation and primary dimension."
    )
    return "\n".join(prompt)


def build_relationship_messages(
    fact_a: FactSchema,
    fact_b: FactSchema,
    entity_a: Optional[EntitySchema] = None,
    entity_b: Optional[EntitySchema] = None,
    deterministic_comparison: Optional[dict[str, Any]] = None,
) -> list[dict[str, str]]:
    """Build full message list for OpenAI chat completion."""
    return [
        {"role": "system", "content": RELATIONSHIP_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_relationship_user_prompt(
                fact_a, fact_b, entity_a, entity_b, deterministic_comparison
            ),
        },
    ]
