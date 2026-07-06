"""Embedding generation and pgvector-backed storage for indexed code chunks (E7-S2)."""

from backend.repository.embeddings.provider import (
    DEFAULT_EMBEDDING_DIMENSION,
    EmbeddingProvider,
    StubEmbeddingProvider,
)

__all__ = ["DEFAULT_EMBEDDING_DIMENSION", "EmbeddingProvider", "StubEmbeddingProvider"]
