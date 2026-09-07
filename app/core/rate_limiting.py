"""Utilities for rate-limiting, error inspection, and timestamp formatting."""

from __future__ import annotations

import datetime
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def extract_retry_delay(exc: Exception | str, default: float = 45.0) -> float:
    """Extract recommended retry delay from Gemini/OpenAI rate-limit error, or fallback to default.

    Handles Google RPC error shapes like:
      - 'Please retry in 43.505708463s.'
      - 'retryDelay': '43s'
      - 'retry_after': 43
    """
    err_str = str(exc)

    # 1. 'Please retry in 43.505708463s'
    m = re.search(r"retry in\s+([\d.]+)\s*s", err_str, re.IGNORECASE)
    if m:
        try:
            return max(float(m.group(1)) + 1.5, 5.0)
        except (ValueError, TypeError):
            pass

    # 2. 'retryDelay': '43s' or retryDelay: 43
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?([\d.]+)", err_str, re.IGNORECASE)
    if m:
        try:
            return max(float(m.group(1)) + 1.5, 5.0)
        except (ValueError, TypeError):
            pass

    # 3. 'retry_after': 43
    m = re.search(r"retry_after['\"]?\s*:\s*['\"]?([\d.]+)", err_str, re.IGNORECASE)
    if m:
        try:
            return max(float(m.group(1)) + 1.5, 5.0)
        except (ValueError, TypeError):
            pass

    return default


def format_local_timestamp(ts: Optional[str]) -> str:
    """Convert UTC or ISO timestamp string into human-readable local time (YYYY-MM-DD HH:MM:SS)."""
    if not ts:
        return ""
    ts_str = str(ts).strip()
    try:
        clean_ts = ts_str.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(clean_ts)
        if dt.tzinfo is None:
            # SQLite default datetime('now') is in UTC
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # Fallback to simple slice formatting if parsing fails
        return ts_str[:19].replace("T", " ")


def compute_duration(start_ts: Optional[str], end_ts: Optional[str]) -> str:
    """Compute human-friendly duration string between two timestamps (e.g. '48s', '2m 35s')."""
    if not start_ts or not end_ts:
        return "-"
    try:
        s = datetime.datetime.fromisoformat(str(start_ts).strip().replace("Z", "+00:00"))
        e = datetime.datetime.fromisoformat(str(end_ts).strip().replace("Z", "+00:00"))
        if s.tzinfo is None:
            s = s.replace(tzinfo=datetime.timezone.utc)
        if e.tzinfo is None:
            e = e.replace(tzinfo=datetime.timezone.utc)
        secs = max(0, int((e - s).total_seconds()))
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        rem_secs = secs % 60
        if rem_secs > 0:
            return f"{mins}m {rem_secs}s"
        return f"{mins}m"
    except Exception:
        return "-"
