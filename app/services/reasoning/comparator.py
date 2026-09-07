"""Deterministic 9-dimension context comparator for fact pairs."""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Optional

from app.models.schemas import (
    EntitySchema,
    EntityType,
    FactSchema,
    PrimaryDimension,
    RelationshipType,
    ValueType,
)
from app.services.reasoning.models import LLMRelationshipClassification

logger = logging.getLogger(__name__)


def _extract_year(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(?:(?:fy|fiscal\s*(?:year)?)\s*)?(20\d{2}|19\d{2})", text.lower())
    return m.group(1) if m else None


def _is_quarter(text: Optional[str]) -> bool:
    if not text:
        return False
    return bool(re.search(r"\bq[1-4]\b|fourth\s*quarter|first\s*quarter|second\s*quarter|third\s*quarter", text.lower()))


class DeterministicComparator:
    """Compares two facts across 9 structured dimensions and determines whether

    an immediate conclusive relationship exists before falling back to LLM.
    """

    def compare(
        self,
        fact_a: FactSchema,
        fact_b: FactSchema,
        entity_a: Optional[EntitySchema] = None,
        entity_b: Optional[EntitySchema] = None,
    ) -> tuple[bool, Optional[LLMRelationshipClassification], dict[str, Any]]:
        """Run 9-dimension comparison.

        Returns:
            (is_conclusive, classification, context_comparison_dict)
        """
        context: dict[str, Any] = {}

        # ── 1. Entity Dimension ─────────────────────────────────────────
        name_a = (entity_a.canonical_name if entity_a else fact_a.subject).strip().lower()
        name_b = (entity_b.canonical_name if entity_b else fact_b.subject).strip().lower()

        type_a = entity_a.entity_type if entity_a else None
        type_b = entity_b.entity_type if entity_b else None

        entity_id_match = bool(fact_a.entity_id and fact_b.entity_id and fact_a.entity_id == fact_b.entity_id)
        entity_name_match = (name_a == name_b) and bool(name_a)
        same_entity = entity_id_match or entity_name_match

        context["entity_a"] = entity_a.canonical_name if entity_a else fact_a.subject
        context["entity_b"] = entity_b.canonical_name if entity_b else fact_b.subject
        context["entity_match"] = same_entity

        # Check entity type incompatibility
        if type_a and type_b and type_a != type_b and type_a != EntityType.OTHER and type_b != EntityType.OTHER:
            context["entity_type_mismatch"] = True
            return True, LLMRelationshipClassification(
                relationship_type=RelationshipType.UNRELATED,
                confidence=1.0,
                primary_dimension=PrimaryDimension.ENTITY,
                explanation=f"Facts describe completely different entity types ({type_a.value} vs {type_b.value}).",
                context_comparison=context,
            ), context

        if not same_entity:
            # Different entities
            return True, LLMRelationshipClassification(
                relationship_type=RelationshipType.UNRELATED,
                confidence=1.0,
                primary_dimension=PrimaryDimension.ENTITY,
                explanation=f"Facts describe different entities: '{context['entity_a']}' vs '{context['entity_b']}'.",
                context_comparison=context,
            ), context

        # ── 2. Predicate Dimension ──────────────────────────────────────
        pred_a = (fact_a.predicate or "").strip().lower()
        pred_b = (fact_b.predicate or "").strip().lower()
        pred_match = (pred_a == pred_b) and bool(pred_a)
        context["predicate_a"] = fact_a.predicate
        context["predicate_b"] = fact_b.predicate
        context["predicate_match"] = pred_match

        # Related predicates like revenue vs sales need LLM judgment
        if not pred_match:
            from app.services.matching.candidates import PREDICATE_FAMILIES

            is_family = False
            for members in PREDICATE_FAMILIES.values():
                if pred_a in members and pred_b in members:
                    is_family = True
                    break

            if is_family:
                context["predicate_family_related"] = True
                # Inconclusive: delegate to LLM to judge semantic equivalence vs reconciliation
                return False, None, context
            else:
                # Disjoint predicates on same entity (e.g. CEO vs Revenue)
                return True, LLMRelationshipClassification(
                    relationship_type=RelationshipType.UNRELATED,
                    confidence=1.0,
                    primary_dimension=PrimaryDimension.DEFINITION,
                    explanation=f"Facts describe unrelated metrics on the same entity: '{fact_a.predicate}' vs '{fact_b.predicate}'.",
                    context_comparison=context,
                ), context

        # ── 3. Unit / Currency Dimension ────────────────────────────────
        curr_a = (fact_a.currency or "").strip().upper()
        curr_b = (fact_b.currency or "").strip().upper()
        unit_a = (fact_a.normalized_unit or fact_a.unit or "").strip().lower()
        unit_b = (fact_b.normalized_unit or fact_b.unit or "").strip().lower()

        context["currency_a"] = curr_a or None
        context["currency_b"] = curr_b or None
        context["unit_a"] = unit_a or None
        context["unit_b"] = unit_b or None

        is_pct_a = fact_a.value_type == ValueType.PERCENTAGE or unit_a == "%"
        is_pct_b = fact_b.value_type == ValueType.PERCENTAGE or unit_b == "%"

        if is_pct_a != is_pct_b:
            context["unit_match"] = False
            context["dimension_mismatch"] = "percentage_vs_monetary"
            return True, LLMRelationshipClassification(
                relationship_type=RelationshipType.RECONCILES,
                confidence=0.95,
                primary_dimension=PrimaryDimension.UNIT,
                explanation=f"Metrics represent different unit dimensions: percentage ({fact_a.value_text if is_pct_a else fact_b.value_text}) vs non-percentage ({fact_b.value_text if is_pct_a else fact_a.value_text}).",
                context_comparison=context,
            ), context

        currency_match = True
        if curr_a and curr_b and curr_a != curr_b:
            currency_match = False
        context["currency_match"] = currency_match

        unit_match = True
        if unit_a and unit_b and unit_a != unit_b:
            unit_match = False
        context["unit_match"] = unit_match and currency_match

        # ── 4. Temporal Dimension ───────────────────────────────────────
        t_text_a = fact_a.time_text or ""
        t_text_b = fact_b.time_text or ""
        year_a = _extract_year(fact_a.time_text) or _extract_year(fact_a.time_start)
        year_b = _extract_year(fact_b.time_text) or _extract_year(fact_b.time_start)
        is_q_a = _is_quarter(fact_a.time_text)
        is_q_b = _is_quarter(fact_b.time_text)

        context["period_a"] = t_text_a or fact_a.time_start
        context["period_b"] = t_text_b or fact_b.time_start

        period_match: Optional[bool] = None
        period_difference_reason: Optional[str] = None

        if year_a and year_b and year_a != year_b:
            period_match = False
            period_difference_reason = f"Different reporting years: {year_a} vs {year_b}"
        elif is_q_a != is_q_b:
            period_match = False
            period_difference_reason = "Quarterly figure vs Full-year figure"
        elif fact_a.time_start and fact_b.time_start:
            if fact_a.time_start == fact_b.time_start and fact_a.time_end == fact_b.time_end:
                period_match = True
            else:
                period_match = False
                period_difference_reason = f"Different date spans: {fact_a.time_start}..{fact_a.time_end} vs {fact_b.time_start}..{fact_b.time_end}"
        elif year_a and year_b and year_a == year_b and not is_q_a and not is_q_b:
            period_match = True

        context["period_match"] = period_match

        # ── 5. Scope & Geography Dimensions ─────────────────────────────
        scope_a = (fact_a.scope or "").strip().lower()
        scope_b = (fact_b.scope or "").strip().lower()
        scope_match = True
        if scope_a and scope_b and scope_a != scope_b:
            scope_match = False
        context["scope_a"] = fact_a.scope
        context["scope_b"] = fact_b.scope
        context["scope_match"] = scope_match

        geo_a = (fact_a.geography or "").strip().lower()
        geo_b = (fact_b.geography or "").strip().lower()
        geo_match = True
        if geo_a and geo_b and geo_a != geo_b:
            geo_match = False
        context["geography_a"] = fact_a.geography
        context["geography_b"] = fact_b.geography
        context["geography_match"] = geo_match

        # ── 6. Qualifiers Dimension ─────────────────────────────────────
        qual_a = set(json.loads(fact_a.qualifiers_json)) if fact_a.qualifiers_json else set()
        qual_b = set(json.loads(fact_b.qualifiers_json)) if fact_b.qualifiers_json else set()
        context["qualifiers_a"] = list(qual_a)
        context["qualifiers_b"] = list(qual_b)

        # ── 7. Value Dimension & Tolerance ──────────────────────────────
        val_a = fact_a.normalized_numeric_value
        val_b = fact_b.normalized_numeric_value
        values_equal = False

        if val_a is not None and val_b is not None:
            denom = max(abs(val_a), abs(val_b), 1e-6)
            rel_diff = abs(val_a - val_b) / denom
            context["relative_value_difference"] = round(rel_diff, 4)
            if rel_diff <= 0.005:  # within 0.5% tolerance
                values_equal = True
        elif fact_a.value_text.strip().lower() == fact_b.value_text.strip().lower():
            values_equal = True

        context["values_equal"] = values_equal

        # ── Deterministic Decision Matrix ───────────────────────────────

        # Scenario 1: Identical context across all dimensions
        if (
            pred_match
            and currency_match
            and unit_match
            and (period_match is True)
            and scope_match
            and geo_match
            and qual_a == qual_b
        ):
            if values_equal:
                # Definite Corroboration
                period_desc = t_text_a or year_a or "the reporting period"
                return True, LLMRelationshipClassification(
                    relationship_type=RelationshipType.CORROBORATES,
                    confidence=1.0,
                    primary_dimension=PrimaryDimension.VALUE,
                    explanation=f"Both sources corroborate that {context['entity_a']} {fact_a.predicate} was {fact_a.value_text} for {period_desc}.",
                    context_comparison=context,
                ), context
            else:
                # Direct Contradiction! Same entity, predicate, units, period, scope, geo, but differing values!
                return True, LLMRelationshipClassification(
                    relationship_type=RelationshipType.CONTRADICTS,
                    confidence=0.95,
                    primary_dimension=PrimaryDimension.VALUE,
                    explanation=(
                        f"Direct contradiction on {context['entity_a']} {fact_a.predicate} for {t_text_a or year_a}: "
                        f"'{fact_a.value_text}' vs '{fact_b.value_text}' under identical scope and period."
                    ),
                    context_comparison=context,
                ), context

        # Scenario 2: Values differ, but a contextual dimension explains the difference -> RECONCILIATION
        if pred_match and not values_equal:
            # Time difference reconciles values
            if period_match is False:
                return True, LLMRelationshipClassification(
                    relationship_type=RelationshipType.RECONCILES,
                    confidence=0.95,
                    primary_dimension=PrimaryDimension.TIME,
                    explanation=(
                        f"Values differ because Fact A reports for {context['period_a'] or 'period A'} "
                        f"while Fact B reports for {context['period_b'] or 'period B'} ({period_difference_reason})."
                    ),
                    context_comparison=context,
                ), context

            # Scope difference reconciles values
            if not scope_match and scope_a and scope_b:
                return True, LLMRelationshipClassification(
                    relationship_type=RelationshipType.RECONCILES,
                    confidence=0.90,
                    primary_dimension=PrimaryDimension.SCOPE,
                    explanation=f"Values differ due to reporting scope: '{fact_a.scope}' vs '{fact_b.scope}'.",
                    context_comparison=context,
                ), context

            # Geography difference reconciles values
            if not geo_match and geo_a and geo_b:
                return True, LLMRelationshipClassification(
                    relationship_type=RelationshipType.RECONCILES,
                    confidence=0.90,
                    primary_dimension=PrimaryDimension.GEOGRAPHY,
                    explanation=f"Values differ due to geographic coverage: '{fact_a.geography}' vs '{fact_b.geography}'.",
                    context_comparison=context,
                ), context

            # Currency / Unit difference reconciles values
            if not currency_match and curr_a and curr_b:
                return True, LLMRelationshipClassification(
                    relationship_type=RelationshipType.RECONCILES,
                    confidence=0.90,
                    primary_dimension=PrimaryDimension.UNIT,
                    explanation=f"Values differ due to currency difference: {curr_a} vs {curr_b}.",
                    context_comparison=context,
                ), context

        # If not deterministically conclusive, return False so the LLM handles semantic nuances
        return False, None, context
