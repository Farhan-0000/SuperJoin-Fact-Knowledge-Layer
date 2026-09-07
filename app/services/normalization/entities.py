"""Canonical entity resolution and alias management.

Enforces critical rule:
NEVER force low-confidence synonym equivalence.
Uncertain entity matches must remain uncertain and distinct.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from app.db.database import get_connection
from app.models.schemas import EntityType

logger = logging.getLogger(__name__)

# Standard legal entity suffixes to strip for canonicalization
LEGAL_SUFFIXES = [
    r"\bcorporation\b",
    r"\bcorp\.?\b",
    r"\bincorporated\b",
    r"\binc\.?\b",
    r"\blimited\b",
    r"\bltd\.?\b",
    r"\bllc\.?\b",
    r"\bl\.l\.c\.?\b",
    r"\bgmbh\b",
    r"\bplc\.?\b",
    r"\bpte\.?\s+ltd\.?\b",
    r"\bs\.a\.?\b",
    r"\ba\.g\.?\b",
]

GENERIC_ENTITY_MENTIONS = {
    "the company", "the group", "the organization", "the firm", "the corporation",
    "management", "board of directors", "company", "group", "we", "our"
}


@dataclass
class ResolvedEntity:
    """Result of resolving an entity mention."""

    entity_id: str
    canonical_name: str
    entity_type: EntityType
    confidence: float
    is_new: bool
    is_uncertain: bool = False


def clean_canonical_name(name: str) -> str:
    """Normalize company and entity names while preserving identity."""
    t = name.strip()
    # Normalize whitespace
    t = re.sub(r"\s+", " ", t)
    return t


def get_base_name(name: str) -> str:
    """Strip standard legal suffixes to find common organizational stem."""
    t = clean_canonical_name(name)
    for suffix_pat in LEGAL_SUFFIXES:
        t = re.sub(suffix_pat, "", t, flags=re.IGNORECASE).strip(" ,.-")
    return t


class EntityResolver:
    """Resolves raw entity mentions to canonical entities and manages aliases."""

    def resolve_entity(
        self,
        name: str,
        entity_type: EntityType = EntityType.ORGANIZATION,
        mention_text: Optional[str] = None,
    ) -> ResolvedEntity:
        """Resolve an entity mention to a canonical entity in the database.

        Args:
            name: Normalized subject string (e.g. 'Acme Corporation').
            entity_type: Declared or inferred entity type.
            mention_text: Raw verbatim mention from source text.

        Returns:
            ResolvedEntity with entity_id and confidence.
        """
        raw_name = clean_canonical_name(name)
        if not raw_name:
            raw_name = "Unknown Entity"

        # Check for generic/anaphoric mentions (e.g. "the company")
        if raw_name.lower() in GENERIC_ENTITY_MENTIONS:
            # Do NOT force merge generic pronouns into arbitrary companies
            return self._create_entity(raw_name, entity_type, confidence=0.5, is_uncertain=True)

        conn = get_connection()
        try:
            # 1. Exact match on canonical_name
            row = conn.execute(
                "SELECT id, canonical_name, entity_type, confidence FROM entities WHERE LOWER(canonical_name) = ?",
                (raw_name.lower(),),
            ).fetchone()
            if row:
                entity_id = row["id"]
                if mention_text and mention_text.lower() != raw_name.lower():
                    self._add_alias_if_missing(conn, entity_id, mention_text, confidence=1.0)
                return ResolvedEntity(
                    entity_id=entity_id,
                    canonical_name=row["canonical_name"],
                    entity_type=EntityType(row["entity_type"]),
                    confidence=row["confidence"],
                    is_new=False,
                )

            # 2. Exact match on existing alias
            alias_row = conn.execute(
                """SELECT e.id, e.canonical_name, e.entity_type, e.confidence
                   FROM entity_aliases a
                   JOIN entities e ON a.entity_id = e.id
                   WHERE LOWER(a.alias) = ?""",
                (raw_name.lower(),),
            ).fetchone()
            if alias_row:
                return ResolvedEntity(
                    entity_id=alias_row["id"],
                    canonical_name=alias_row["canonical_name"],
                    entity_type=EntityType(alias_row["entity_type"]),
                    confidence=alias_row["confidence"],
                    is_new=False,
                )

            # 3. High-confidence legal stem match (e.g. "Acme Corp." -> "Acme Corporation")
            base_name = get_base_name(raw_name)
            if len(base_name) >= 3:
                candidates = conn.execute(
                    "SELECT id, canonical_name, entity_type FROM entities"
                ).fetchall()
                for c in candidates:
                    c_base = get_base_name(c["canonical_name"])
                    if base_name.lower() == c_base.lower():
                        # High confidence stem match between legal variations
                        entity_id = c["id"]
                        self._add_alias_if_missing(conn, entity_id, raw_name, confidence=0.95)
                        if mention_text:
                            self._add_alias_if_missing(conn, entity_id, mention_text, confidence=0.95)
                        conn.commit()
                        return ResolvedEntity(
                            entity_id=entity_id,
                            canonical_name=c["canonical_name"],
                            entity_type=EntityType(c["entity_type"]),
                            confidence=0.95,
                            is_new=False,
                        )

            # 4. No high-confidence match found — create new canonical entity
            # CRITICAL RULE: NEVER force low-confidence merges.
            return self._create_entity(raw_name, entity_type, confidence=1.0, is_uncertain=False)
        finally:
            conn.close()

    def _create_entity(
        self,
        canonical_name: str,
        entity_type: EntityType,
        confidence: float = 1.0,
        is_uncertain: bool = False,
    ) -> ResolvedEntity:
        """Create and persist a new canonical entity in SQLite."""
        entity_id = str(uuid.uuid4())
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO entities (id, canonical_name, entity_type, confidence)
                   VALUES (?, ?, ?, ?)""",
                (entity_id, canonical_name, entity_type.value, confidence),
            )
            # Add self as initial alias
            conn.execute(
                """INSERT INTO entity_aliases (id, entity_id, alias, confidence)
                   VALUES (?, ?, ?, ?)""",
                (str(uuid.uuid4()), entity_id, canonical_name, 1.0),
            )
            conn.commit()
            return ResolvedEntity(
                entity_id=entity_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
                confidence=confidence,
                is_new=True,
                is_uncertain=is_uncertain,
            )
        finally:
            conn.close()

    def _add_alias_if_missing(
        self, conn: Any, entity_id: str, alias: str, confidence: float = 1.0
    ) -> None:
        """Record an alias if not already present."""
        clean = clean_canonical_name(alias)
        if not clean:
            return
        row = conn.execute(
            "SELECT id FROM entity_aliases WHERE entity_id = ? AND LOWER(alias) = ?",
            (entity_id, clean.lower()),
        ).fetchone()
        if not row:
            conn.execute(
                """INSERT INTO entity_aliases (id, entity_id, alias, confidence)
                   VALUES (?, ?, ?, ?)""",
                (str(uuid.uuid4()), entity_id, clean, confidence),
            )
