"""Pluggable embedding provider abstraction (E7-S2-T1/T4).

``EmbeddingProvider`` is the extension point new providers implement:
``embed(texts) -> list[vector]`` plus a ``dimension`` property.
:class:`StubEmbeddingProvider` is the deterministic, dependency-free default
used in local-first mode when no external embedding API is configured
(E7-S2-T4) — same text always yields the same vector, but the vectors carry
no real semantic meaning. A real external provider (OpenAI, a local model
server, etc.) is a future extension implementing the same Protocol; no
external API call is wired up here, matching how
:class:`~backend.repository.providers.treesitter_provider.TreeSitterProvider`
guards on an optional real dependency.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable

#: Default vector length for :class:`StubEmbeddingProvider`, and the
#: dimension the ``code_embeddings.embedding`` pgvector column is created
#: with (``backend/persistence/migrations/postgres_versions.py``). pgvector
#: requires a fixed dimension per column; keep these in sync if either
#: changes (see ADR-011).
DEFAULT_EMBEDDING_DIMENSION = 128


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Structural Protocol for embedding providers."""

    @property
    def dimension(self) -> int:
        """Return the fixed length of every vector this provider returns."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, in the same order."""
        ...


class StubEmbeddingProvider:
    """Deterministic, dependency-free local embedding provider.

    Hashes each input text into ``dimension`` pseudo-random-but-deterministic
    floats, then L2-normalizes the result (so cosine/inner-product distance
    behaves sensibly against pgvector). This is a placeholder for local-first
    mode and tests, not a real semantic embedding model — swap in a real
    :class:`EmbeddingProvider` implementation for meaningful retrieval quality.
    """

    def __init__(self, dimension: int = DEFAULT_EMBEDDING_DIMENSION) -> None:
        """Initialize the provider with a fixed output dimension.

        Args:
            dimension: Length of every vector returned by :meth:`embed`.

        Raises:
            ValueError: If ``dimension`` is not positive.
        """
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        """Return the fixed vector length configured at construction."""
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one deterministic, L2-normalized vector per input text.

        Args:
            texts: Input strings to embed.

        Returns:
            One ``dimension``-length vector per input text, in the same order.
        """
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        """Hash *text* into a deterministic, L2-normalized vector of length :attr:`dimension`."""
        raw: list[float] = []
        counter = 0
        while len(raw) < self._dimension:
            digest = hashlib.sha256(f"{text}:{counter}".encode("utf-8")).digest()
            for offset in range(0, len(digest) - 3, 4):
                if len(raw) >= self._dimension:
                    break
                as_uint32 = int.from_bytes(digest[offset : offset + 4], "big", signed=False)
                raw.append((as_uint32 / 0xFFFFFFFF) * 2 - 1)  # map to [-1, 1]
            counter += 1
        norm = math.sqrt(sum(value * value for value in raw)) or 1.0
        return [value / norm for value in raw]


__all__ = ["DEFAULT_EMBEDDING_DIMENSION", "EmbeddingProvider", "StubEmbeddingProvider"]
