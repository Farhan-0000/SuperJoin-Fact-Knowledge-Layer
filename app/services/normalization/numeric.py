"""Deterministic numeric, currency, unit, and percentage normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.models.schemas import ValueType

# Multiplier table for word/letter magnitudes
MAGNITUDE_MULTIPLIERS = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "thousands": 1_000.0,
    "m": 1_000_000.0,
    "mn": 1_000_000.0,
    "mio": 1_000_000.0,
    "million": 1_000_000.0,
    "millions": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
    "billions": 1_000_000_000.0,
    "t": 1_000_000_000_000.0,
    "tn": 1_000_000_000_000.0,
    "trillion": 1_000_000_000_000.0,
    "trillions": 1_000_000_000_000.0,
}

# Currency symbol mapping
CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "c$": "CAD",
    "a$": "AUD",
    "₩": "KRW",
    "chf": "CHF",
}

CURRENCY_CODES = {
    "usd", "eur", "gbp", "jpy", "inr", "cad", "aud", "cny", "chf", "sek", "nok", "krw"
}


@dataclass
class NumericNormalizationResult:
    """Result of deterministic numeric normalization."""

    raw_numeric: Optional[float]
    normalized_numeric: Optional[float]
    unit: Optional[str]
    normalized_unit: Optional[str]
    currency: Optional[str]
    value_type: ValueType


def normalize_numeric(
    value_text: str,
    declared_unit: Optional[str] = None,
    declared_currency: Optional[str] = None,
    declared_type: Optional[ValueType] = None,
) -> NumericNormalizationResult:
    """Deterministically parse and normalize numerical strings:

    - Thousands, millions, billions, trillions
    - Comma-separated numbers
    - Currency symbols and codes
    - Percentages
    - Ratios
    """
    text = value_text.strip()
    if not text:
        return NumericNormalizationResult(
            raw_numeric=None,
            normalized_numeric=None,
            unit=declared_unit,
            normalized_unit=declared_unit,
            currency=declared_currency,
            value_type=declared_type or ValueType.TEXT,
        )

    clean_text = text.lower()

    # ── 1. Detect and strip Currency ──────────────────────────────
    detected_currency = declared_currency

    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in clean_text:
            detected_currency = code
            clean_text = clean_text.replace(symbol, " ")

    for code in CURRENCY_CODES:
        # Match standalone code e.g. "120 usd" or "usd 120"
        pattern = rf"\b{code}\b"
        if re.search(pattern, clean_text):
            detected_currency = code.upper()
            clean_text = re.sub(pattern, " ", clean_text)

    # ── 2. Detect Percentage ──────────────────────────────────────
    is_percentage = (
        "%" in clean_text
        or "percent" in clean_text
        or "pct" in clean_text
        or declared_type == ValueType.PERCENTAGE
        or (declared_unit and "%" in declared_unit)
    )

    clean_text = clean_text.replace("%", " ").replace("percentage", " ").replace("percent", " ").replace("pct", " ")

    # ── 3. Detect Ratio (e.g. "1:2" or "3/4") ─────────────────────
    ratio_colon = re.search(r"^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$", clean_text)
    if ratio_colon:
        num = float(ratio_colon.group(1))
        denom = float(ratio_colon.group(2))
        val = num / denom if denom != 0 else None
        return NumericNormalizationResult(
            raw_numeric=val,
            normalized_numeric=val,
            unit="ratio",
            normalized_unit="ratio",
            currency=detected_currency,
            value_type=ValueType.RANGE,
        )

    # ── 4. Detect Multiplier (e.g. billion, million, k) ───────────
    multiplier = 1.0
    detected_unit = declared_unit
    normalized_unit = declared_unit

    # Match tokens for magnitude words
    words = clean_text.split()
    remaining_tokens = []
    for w in words:
        w_clean = w.strip(".,;:()")
        if w_clean in MAGNITUDE_MULTIPLIERS:
            multiplier *= MAGNITUDE_MULTIPLIERS[w_clean]
        else:
            remaining_tokens.append(w)

    clean_text = " ".join(remaining_tokens)

    # Also handle attached suffixes like "1.2B" or "120M" or "50k"
    suffix_match = re.search(r"(\d+(?:\.\d+)?)\s*([kmbt])\b", clean_text)
    if suffix_match:
        suf = suffix_match.group(2)
        if suf in MAGNITUDE_MULTIPLIERS and multiplier == 1.0:
            multiplier = MAGNITUDE_MULTIPLIERS[suf]
            clean_text = clean_text[:suffix_match.start(2)] + clean_text[suffix_match.end(2):]

    # ── 5. Extract Core Numeric Value ─────────────────────────────
    # Remove commas between digits e.g. 1,200,000 -> 1200000
    num_str = re.sub(r"(?<=\d),(?=\d)", "", clean_text)

    # Find the primary decimal/integer number
    num_match = re.search(r"[-+]?\d*\.?\d+", num_str)
    if not num_match:
        return NumericNormalizationResult(
            raw_numeric=None,
            normalized_numeric=None,
            unit=declared_unit,
            normalized_unit=declared_unit,
            currency=detected_currency,
            value_type=declared_type or ValueType.TEXT,
        )

    try:
        base_value = float(num_match.group(0))
    except ValueError:
        return NumericNormalizationResult(
            raw_numeric=None,
            normalized_numeric=None,
            unit=declared_unit,
            normalized_unit=declared_unit,
            currency=detected_currency,
            value_type=declared_type or ValueType.TEXT,
        )

    # ── 6. Compute Normalized Values ──────────────────────────────
    if is_percentage:
        value_type = ValueType.PERCENTAGE
        raw_numeric = base_value
        # If expressed like 2.5%, normalized ratio is 0.025
        # If already expressed as 0.025, leave as 0.025
        normalized_numeric = round(base_value / 100.0 if base_value > 1.0 else base_value, 6)
        unit = "%"
        normalized_unit = "%"
    elif detected_currency:
        value_type = ValueType.CURRENCY
        raw_numeric = base_value
        normalized_numeric = round(base_value * multiplier, 2)
        unit = detected_currency
        normalized_unit = detected_currency
    else:
        value_type = declared_type or ValueType.NUMBER
        raw_numeric = base_value
        normalized_numeric = base_value * multiplier
        if multiplier > 1.0 and not normalized_unit:
            normalized_unit = declared_unit or None

    return NumericNormalizationResult(
        raw_numeric=raw_numeric,
        normalized_numeric=normalized_numeric,
        unit=unit if is_percentage or detected_currency else declared_unit,
        normalized_unit=normalized_unit,
        currency=detected_currency,
        value_type=value_type,
    )
