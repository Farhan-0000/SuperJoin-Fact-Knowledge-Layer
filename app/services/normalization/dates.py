"""Deterministic date, period, and fiscal year normalization.

Enforces critical rule:
Do NOT infer exact fiscal-year boundaries unless supported by document context.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.models.schemas import TimeGranularity

MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


@dataclass
class DateNormalizationResult:
    """Result of deterministic date/temporal normalization."""

    time_text: Optional[str]
    time_start: Optional[str]
    time_end: Optional[str]
    time_granularity: Optional[TimeGranularity]


def normalize_date_period(
    time_text: Optional[str],
    document_context: Optional[dict[str, Any]] = None,
) -> DateNormalizationResult:
    """Deterministically parse and normalize dates and periods.

    Args:
        time_text: Raw temporal string from text (e.g. 'FY2025', 'Q3 2024', '2023-2025').
        document_context: Optional metadata containing confirmed fiscal calendar rules
                          (e.g. {'fiscal_year_end': '03-31'}).

    Returns:
        DateNormalizationResult with normalized string and optional ISO bounds.
    """
    if not time_text or not time_text.strip():
        return DateNormalizationResult(
            time_text=None,
            time_start=None,
            time_end=None,
            time_granularity=None,
        )

    text = time_text.strip()
    clean = re.sub(r"\s+", " ", text)

    # ── 1. Fiscal Year Detection (e.g. "FY2025", "FY 2025", "FY25") ──
    fy_match = re.search(r"\b(?:FY|Fiscal(?:\s+Year)?)\s*['’]?(\d{2,4})\b", clean, re.IGNORECASE)
    if fy_match:
        year_str = fy_match.group(1)
        full_year = int(year_str) if len(year_str) == 4 else 2000 + int(year_str)
        canonical_fy = f"FY{full_year}"

        # Check if quarter is attached (e.g. "Q1 FY2025")
        q_match = re.search(r"\bQ([1-4])\b", clean, re.IGNORECASE)
        if q_match:
            q_num = int(q_match.group(1))
            canonical_time = f"Q{q_num} {canonical_fy}"
            return DateNormalizationResult(
                time_text=canonical_time,
                time_start=None,
                time_end=None,
                time_granularity=TimeGranularity.QUARTER,
            )

        # CRITICAL RULE:
        # Do NOT infer exact fiscal-year boundaries unless supported by document context.
        time_start = None
        time_end = None
        if document_context and "fiscal_year_end" in document_context:
            fy_end = document_context["fiscal_year_end"]  # e.g. "03-31"
            if fy_end == "03-31":
                time_start = f"{full_year - 1}-04-01"
                time_end = f"{full_year}-03-31"
            elif fy_end == "12-31":
                time_start = f"{full_year}-01-01"
                time_end = f"{full_year}-12-31"

        return DateNormalizationResult(
            time_text=canonical_fy,
            time_start=time_start,
            time_end=time_end,
            time_granularity=TimeGranularity.FISCAL_YEAR,
        )

    # ── 2. Explicit Date Range (e.g. "2023 - 2025" or "2023 to 2024") ──
    range_match = re.search(r"\b(19\d\d|20\d\d)\s*(?:-|–|—|to)\s*(19\d\d|20\d\d)\b", clean)
    if range_match:
        y1, y2 = int(range_match.group(1)), int(range_match.group(2))
        return DateNormalizationResult(
            time_text=f"{y1}-{y2}",
            time_start=f"{y1}-01-01",
            time_end=f"{y2}-12-31",
            time_granularity=TimeGranularity.YEAR,
        )

    # ── 3. Calendar Quarter (e.g. "Q1 2024", "4Q 2023") ──────────────
    cq_match = re.search(r"\b(?:Q([1-4])\s*(19\d\d|20\d\d)|([1-4])Q\s*(19\d\d|20\d\d))\b", clean, re.IGNORECASE)
    if cq_match:
        q_num = int(cq_match.group(1) or cq_match.group(3))
        year = int(cq_match.group(2) or cq_match.group(4))

        start_months = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}
        end_months = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}

        return DateNormalizationResult(
            time_text=f"Q{q_num} {year}",
            time_start=f"{year}-{start_months[q_num]}",
            time_end=f"{year}-{end_months[q_num]}",
            time_granularity=TimeGranularity.QUARTER,
        )

    # ── 4. Month and Year (e.g. "March 2024", "Mar 2024", "2024-03") ─
    month_year_match = re.search(r"\b([a-zA-Z]+)\s+(19\d\d|20\d\d)\b", clean)
    if month_year_match:
        m_str = month_year_match.group(1).lower()
        if m_str in MONTH_NAMES:
            m_num = MONTH_NAMES[m_str]
            year = int(month_year_match.group(2))
            last_day = calendar.monthrange(year, m_num)[1]
            return DateNormalizationResult(
                time_text=f"{calendar.month_name[m_num]} {year}",
                time_start=f"{year}-{m_num:02d}-01",
                time_end=f"{year}-{m_num:02d}-{last_day:02d}",
                time_granularity=TimeGranularity.MONTH,
            )

    # ── 5. Standalone Calendar Year (e.g. "2024", "2025") ────────────
    year_match = re.search(r"\b(19\d\d|20\d\d)\b", clean)
    if year_match:
        year = int(year_match.group(1))
        return DateNormalizationResult(
            time_text=str(year),
            time_start=f"{year}-01-01",
            time_end=f"{year}-12-31",
            time_granularity=TimeGranularity.YEAR,
        )

    # Fallback: preserve original text without inventing dates
    return DateNormalizationResult(
        time_text=clean,
        time_start=None,
        time_end=None,
        time_granularity=TimeGranularity.UNKNOWN,
    )
