"""Tests for rate limiting delay extraction and local timestamp formatting."""

import datetime
from app.core.rate_limiting import compute_duration, extract_retry_delay, format_local_timestamp


def test_extract_retry_delay_from_message() -> None:
    msg = (
        "Job failed: Error code: 429 - {'error': {'code': 429, 'message': "
        "'You exceeded your current quota... Please retry in 43.505708463s.', 'status': 'RESOURCE_EXHAUSTED'}}"
    )
    delay = extract_retry_delay(msg, default=45.0)
    assert 44.0 <= delay <= 46.0


def test_extract_retry_delay_from_retry_info() -> None:
    msg = "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '35s'}"
    delay = extract_retry_delay(msg, default=45.0)
    assert 36.0 <= delay <= 37.0


def test_extract_retry_delay_fallback() -> None:
    msg = "Generic rate limit error without retry hints"
    delay = extract_retry_delay(msg, default=45.0)
    assert delay == 45.0


def test_format_local_timestamp() -> None:
    # None or empty
    assert format_local_timestamp(None) == ""
    assert format_local_timestamp("") == ""

    # ISO UTC
    formatted = format_local_timestamp("2026-09-07T18:47:28+00:00")
    assert len(formatted) == 19
    assert "-" in formatted and ":" in formatted

    # SQLite now format (assumed UTC)
    formatted2 = format_local_timestamp("2026-09-07 18:47:28")
    assert len(formatted2) == 19
    assert "-" in formatted2 and ":" in formatted2


def test_compute_duration() -> None:
    # Less than a minute
    dur = compute_duration("2026-09-07 18:47:28", "2026-09-07 18:48:16")
    assert dur == "48s"

    # Multiple minutes
    dur2 = compute_duration("2026-09-07 18:12:43", "2026-09-07 18:27:02")
    assert dur2 == "14m 19s"

    # None or missing
    assert compute_duration(None, "2026-09-07 18:48:16") == "-"
    assert compute_duration("2026-09-07 18:47:28", None) == "-"
