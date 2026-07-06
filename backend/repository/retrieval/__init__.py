"""Hybrid (lexical + vector) code retrieval for the Context/RAG Service (E7-S3)."""

from backend.repository.retrieval.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion
from backend.repository.retrieval.retriever import RetrievalFilters, RetrievalMode, Snippet, retrieve

__all__ = [
    "DEFAULT_RRF_K",
    "RetrievalFilters",
    "RetrievalMode",
    "Snippet",
    "reciprocal_rank_fusion",
    "retrieve",
]
