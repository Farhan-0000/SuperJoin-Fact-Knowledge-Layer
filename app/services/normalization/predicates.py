"""Predicate normalization with conservative synonym mapping.

CRITICAL RULE:
NEVER force low-confidence synonym equivalence.
For example, 'revenue' and 'sales' may be related metrics, but are NOT automatically identical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class PredicateNormalizationResult:
    """Result of predicate normalization."""

    raw_predicate: str
    canonical_predicate: str
    confidence: float
    is_standardized: bool


# Exact synonym clusters for standardized financial and business metrics.
# Distinct metrics like 'revenue' vs 'sales' are intentionally separated.
CANONICAL_PREDICATE_MAP: dict[str, str] = {
    # Revenue cluster
    "revenue": "revenue",
    "revenues": "revenue",
    "total_revenue": "revenue",
    "total_revenues": "revenue",
    "gross_revenue": "revenue",
    "annual_revenue": "revenue",

    # Sales cluster (kept separate from revenue)
    "sales": "sales",
    "total_sales": "sales",
    "gross_sales": "sales",
    "net_sales": "sales",
    "product_sales": "sales",

    # Operating income cluster
    "operating_income": "operating_income",
    "operating_profit": "operating_income",
    "operating_earnings": "operating_income",
    "ebit": "operating_income",

    # Margins
    "operating_margin": "operating_margin",
    "operating_profit_margin": "operating_margin",
    "gross_margin": "gross_margin",
    "net_margin": "net_margin",

    # Net income cluster
    "net_income": "net_income",
    "net_profit": "net_income",
    "net_earnings": "net_income",

    # People / Headcount
    "employee_count": "employee_count",
    "headcount": "employee_count",
    "total_employees": "employee_count",
    "number_of_employees": "employee_count",
    "workforce": "employee_count",

    # Per-share metrics
    "eps": "eps",
    "earnings_per_share": "eps",
    "diluted_eps": "eps",
    "basic_eps": "eps",

    # Corporate roles
    "ceo": "chief_executive_officer",
    "chief_executive_officer": "chief_executive_officer",
    "cfo": "chief_financial_officer",
    "chief_financial_officer": "chief_financial_officer",
    "founder": "founder",
    "chairman": "chairman",
}


def normalize_predicate(raw_predicate: str) -> PredicateNormalizationResult:
    """Normalize a predicate to its canonical concept without forcing uncertain merges.

    Args:
        raw_predicate: Raw predicate string from extraction (e.g. 'total_revenue', 'Sales').

    Returns:
        PredicateNormalizationResult with canonical predicate and confidence.
    """
    clean = raw_predicate.strip().lower()
    # Replace spaces, hyphens, and slashes with underscores
    clean = re.sub(r"[\s\-\/]+", "_", clean)
    clean = re.sub(r"[^\w_]", "", clean).strip("_")

    if not clean:
        return PredicateNormalizationResult(
            raw_predicate=raw_predicate,
            canonical_predicate="unknown_predicate",
            confidence=0.5,
            is_standardized=False,
        )

    # Check canonical map
    if clean in CANONICAL_PREDICATE_MAP:
        return PredicateNormalizationResult(
            raw_predicate=raw_predicate,
            canonical_predicate=CANONICAL_PREDICATE_MAP[clean],
            confidence=1.0,
            is_standardized=True,
        )

    # If no high-confidence cluster match, retain the cleaned predicate as-is
    return PredicateNormalizationResult(
        raw_predicate=raw_predicate,
        canonical_predicate=clean,
        confidence=0.85,
        is_standardized=False,
    )
