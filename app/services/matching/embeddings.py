"""Embedding service for canonical fact representation and semantic similarity retrieval."""

from __future__ import annotations

import abc
import hashlib
import json
import logging
import math
import struct
import uuid
from typing import Optional

from app.config import get_settings
from app.db.database import get_connection
from app.models.schemas import FactEmbeddingSchema, FactSchema

logger = logging.getLogger(__name__)


# ── Canonical Representation ─────────────────────────────────────────


def build_canonical_representation(
    fact: FactSchema, canonical_entity_name: Optional[str] = None
) -> str:
    """Build canonical representation for semantic candidate retrieval.

    Format:
    canonical subject/entity; predicate; value type; relevant temporal context; scope; geography; qualifiers
    """
    subject = (canonical_entity_name or fact.subject or "").strip()
    predicate = (fact.predicate or "").strip()
    val_type = (
        fact.value_type.value
        if hasattr(fact.value_type, "value")
        else str(fact.value_type)
    )

    # Relevant temporal context
    temp_parts = []
    if fact.time_text:
        temp_parts.append(fact.time_text.strip())
    if fact.time_start or fact.time_end:
        span = f"{fact.time_start or ''}..{fact.time_end or ''}".strip(".")
        if span and span not in temp_parts:
            temp_parts.append(span)
    temporal_str = ", ".join(temp_parts) if temp_parts else "unspecified time"

    scope_str = (fact.scope or "").strip() or "unspecified scope"
    geo_str = (fact.geography or "").strip() or "unspecified geography"

    # Qualifiers
    qualifiers: list[str] = []
    if fact.qualifiers_json:
        try:
            parsed = json.loads(fact.qualifiers_json)
            if isinstance(parsed, list):
                qualifiers = [str(q).strip() for q in parsed if str(q).strip()]
            elif isinstance(parsed, str) and parsed.strip():
                qualifiers = [parsed.strip()]
        except Exception:
            if fact.qualifiers_json.strip():
                qualifiers = [fact.qualifiers_json.strip()]
    qual_str = ", ".join(qualifiers) if qualifiers else "no qualifiers"

    return (
        f"{subject}; {predicate}; {val_type}; {temporal_str}; "
        f"{scope_str}; {geo_str}; {qual_str}"
    )


# ── Vector Serialization & Cosine Similarity ─────────────────────────


def serialize_vector(vector: list[float]) -> bytes:
    """Serialize float vector into compact binary IEEE-754 32-bit floats."""
    return struct.pack(f"{len(vector)}f", *vector)


def deserialize_vector(blob: bytes) -> list[float]:
    """Deserialize binary blob back into float vector."""
    if not blob:
        return []
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors in [-1.0, 1.0]."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0

    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b

    if norm1 <= 0.0 or norm2 <= 0.0:
        return 0.0

    sim = dot / (math.sqrt(norm1) * math.sqrt(norm2))
    return max(-1.0, min(1.0, float(sim)))


# ── Embedding Providers ───────────────────────────────────────────────


class BaseEmbeddingProvider(abc.ABC):
    """Abstract interface for embedding generation."""

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def dimensions(self) -> int:
        ...

    @abc.abstractmethod
    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Synchronously compute embedding vectors for a batch of strings."""
        ...


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """Production provider using OpenAI embeddings API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
    ):
        settings = get_settings()
        self._api_key = api_key or settings.effective_api_key
        self._base_url = settings.resolved_base_url
        self._model = model or settings.resolved_embedding_model or "text-embedding-3-small"
        if "text-embedding-3-small" in self._model:
            default_dim = 1536
        elif "gemini-embedding" in self._model:
            default_dim = 3072
        else:
            default_dim = 3072
        self._dimensions = dimensions or default_dim

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    # Gemini embedding API hard-caps at 100 items per batch request.
    _GEMINI_MAX_BATCH = 100

    def _embed_batch_with_retry(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch (≤100 items) with retry + backoff."""
        import time
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        kwargs: dict = {"input": texts, "model": self._model}
        if "text-embedding-3" in self._model and self._dimensions:
            kwargs["dimensions"] = self._dimensions

        max_retries = 3
        delay = 5.0 if get_settings().is_gemini else 1.0

        for attempt in range(max_retries):
            try:
                response = client.embeddings.create(**kwargs)
                return [item.embedding for item in response.data]
            except Exception as exc:
                err_str = str(exc)
                if (
                    "RateLimit" in type(exc).__name__
                    or "429" in err_str
                    or "RESOURCE_EXHAUSTED" in err_str
                ) and attempt < max_retries - 1:
                    logger.warning(
                        "Rate limit on embeddings (attempt %d/%d). Backing off %.1fs: %s",
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                    delay *= 2.0
                elif attempt < max_retries - 1:
                    logger.warning(
                        "Transient error on embeddings (attempt %d/%d): %s. Retrying in 1s...",
                        attempt + 1,
                        max_retries,
                        exc,
                    )
                    time.sleep(1.0)
                else:
                    raise
        return []  # unreachable, keeps type-checker happy

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI/Gemini embeddings API, automatically sub-batching for Gemini's 100-item limit."""
        import time

        if not texts:
            return []

        is_gemini = get_settings().is_gemini
        batch_size = min(self._GEMINI_MAX_BATCH, len(texts)) if is_gemini else len(texts)

        all_vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            vectors = self._embed_batch_with_retry(chunk)
            all_vectors.extend(vectors)
            # Pace between sub-batches on Gemini to avoid RPM spikes
            if is_gemini and start + batch_size < len(texts):
                time.sleep(2.0)

        return all_vectors


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic offline embedding provider for test suite and local environments.

    Projects text into a unit-normalized vector where overlapping tokens
    and character n-grams yield consistent, semantically meaningful cosine similarities.
    """

    def __init__(self, dimensions: int = 128, model: str = "mock-embedding-v1"):
        self._dimensions = dimensions
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _embed_single(self, text: str) -> list[float]:
        vec = [0.0] * self._dimensions
        if not text.strip():
            return vec

        # Tokenize words and character 3-grams
        tokens = text.lower().replace(";", " ").replace(",", " ").split()
        features = list(tokens)
        for t in tokens:
            if len(t) >= 3:
                for i in range(len(t) - 2):
                    features.append(t[i : i + 3])

        for feat in features:
            h = hashlib.sha256(feat.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self._dimensions
            sign = 1.0 if (h[4] % 2 == 0) else -1.0
            vec[idx] += sign

        # Unit normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_single(t) for t in texts]


# ── Embedding Service ─────────────────────────────────────────────────


class EmbeddingService:
    """Service for computing, caching, and persisting fact embeddings in SQLite."""

    def __init__(
        self,
        provider: Optional[BaseEmbeddingProvider] = None,
        db_path: Optional[str] = None,
    ):
        if provider is not None:
            self.provider = provider
        else:
            settings = get_settings()
            if settings.openai_api_key and not settings.openai_api_key.startswith("sk-test-"):
                self.provider = OpenAIEmbeddingProvider()
            else:
                self.provider = MockEmbeddingProvider()
        self.db_path = db_path

    def embed_facts(
        self,
        facts: list[FactSchema],
        entity_name_lookup: Optional[dict[str, str]] = None,
    ) -> list[FactEmbeddingSchema]:
        """Generate and persist embeddings for a list of facts.

        Skips re-embedding if content hash matches existing record.
        """
        if not facts:
            return []

        entity_lookup = entity_name_lookup or {}
        conn = get_connection(self.db_path)
        try:
            # 1. Build canonical texts and hashes
            canonical_items: list[tuple[FactSchema, str, str]] = []
            for f in facts:
                canonical_entity = entity_lookup.get(f.entity_id or "", None)
                rep = build_canonical_representation(f, canonical_entity)
                chash = hashlib.sha256(rep.encode("utf-8")).hexdigest()
                canonical_items.append((f, rep, chash))

            # 2. Check existing embeddings
            results: list[FactEmbeddingSchema] = []
            to_compute: list[tuple[FactSchema, str, str]] = []

            for f, rep, chash in canonical_items:
                row = conn.execute(
                    """SELECT id, fact_id, model, dimensions, vector_blob, content_hash, created_at
                       FROM fact_embeddings
                       WHERE fact_id = ? AND model = ?""",
                    (f.id, self.provider.model_name),
                ).fetchone()

                if row and row["content_hash"] == chash and row["vector_blob"]:
                    results.append(
                        FactEmbeddingSchema(
                            id=row["id"],
                            fact_id=row["fact_id"],
                            model=row["model"],
                            dimensions=row["dimensions"],
                            vector_blob=row["vector_blob"],
                            content_hash=row["content_hash"],
                            created_at=row["created_at"],
                        )
                    )
                else:
                    to_compute.append((f, rep, chash))

            # 3. Compute new embeddings in batch
            if to_compute:
                texts = [item[1] for item in to_compute]
                vectors = self.provider.get_embeddings(texts)

                for (f, rep, chash), vec in zip(to_compute, vectors):
                    blob = serialize_vector(vec)
                    emb_id = str(uuid.uuid4())
                    conn.execute(
                        """INSERT INTO fact_embeddings (id, fact_id, model, dimensions, vector_blob, content_hash)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(fact_id, model) DO UPDATE SET
                               dimensions=excluded.dimensions,
                               vector_blob=excluded.vector_blob,
                               content_hash=excluded.content_hash,
                               created_at=datetime('now')""",
                        (
                            emb_id,
                            f.id,
                            self.provider.model_name,
                            len(vec),
                            blob,
                            chash,
                        ),
                    )
                    results.append(
                        FactEmbeddingSchema(
                            id=emb_id,
                            fact_id=f.id,
                            model=self.provider.model_name,
                            dimensions=len(vec),
                            vector_blob=blob,
                            content_hash=chash,
                        )
                    )
                conn.commit()

            return results
        finally:
            conn.close()

    def embed_fact(
        self, fact: FactSchema, canonical_entity_name: Optional[str] = None
    ) -> FactEmbeddingSchema:
        """Embed a single fact."""
        lookup = {fact.entity_id: canonical_entity_name} if fact.entity_id and canonical_entity_name else {}
        results = self.embed_facts([fact], lookup)
        return results[0]

    def get_fact_embedding(self, fact_id: str) -> Optional[list[float]]:
        """Retrieve deserialized float vector for a given fact ID."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """SELECT vector_blob FROM fact_embeddings
                   WHERE fact_id = ? AND model = ?""",
                (fact_id, self.provider.model_name),
            ).fetchone()
            if row and row["vector_blob"]:
                return deserialize_vector(row["vector_blob"])
            return None
        finally:
            conn.close()

    def get_fact_embeddings_batch(
        self, fact_ids: list[str]
    ) -> dict[str, list[float]]:
        """Retrieve dictionary of fact_id -> deserialized vector for a list of fact IDs."""
        if not fact_ids:
            return {}
        conn = get_connection(self.db_path)
        try:
            placeholders = ",".join("?" for _ in fact_ids)
            rows = conn.execute(
                f"""SELECT fact_id, vector_blob FROM fact_embeddings
                    WHERE fact_id IN ({placeholders}) AND model = ?""",
                (*fact_ids, self.provider.model_name),
            ).fetchall()
            return {
                r["fact_id"]: deserialize_vector(r["vector_blob"])
                for r in rows
                if r["vector_blob"]
            }
        finally:
            conn.close()
