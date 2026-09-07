"""Tokenizer utility for token counting using tiktoken with fallback."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_ENCODER = None
_ENCODER_TRIED = False


def _get_encoder():
    global _ENCODER, _ENCODER_TRIED
    if not _ENCODER_TRIED:
        _ENCODER_TRIED = True
        try:
            import tiktoken
            # cl100k_base is used by text-embedding-3-small and GPT-4 models
            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception as exc:
            logger.warning("Failed to initialize tiktoken encoder: %s. Using heuristic fallback.", exc)
            _ENCODER = None
    return _ENCODER


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken cl100k_base encoding.

    Falls back to a 4-characters-per-token heuristic if tiktoken is unavailable.
    """
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:
            pass
    # Standard 4 chars per token fallback
    return max(1, len(text) // 4)
