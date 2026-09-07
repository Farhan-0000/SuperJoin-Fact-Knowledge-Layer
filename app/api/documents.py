"""Document management routes (upload placeholder)."""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


# Upload, list, and detail endpoints will be added in Phase 2.
