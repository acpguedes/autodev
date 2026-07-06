"""Hybrid retrieval contract (E7-S3-T3/T4): ``retrieve(query, filters, budget) -> list[Snippet]``.

Combines lexical (:mod:`backend.repository.retrieval.lexical`) and vector
(:mod:`backend.repository.embeddings.pgvector_store`) retrieval via
Reciprocal Rank Fusion (:mod:`backend.repository.retrieval.fusion`),
truncating results to an optional token budget by relevance (the
lowest-scoring snippets are dropped first). Every result carries its score
and source attribution (file path + line span + which mode(s) surfaced it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.repository.embeddings.pgvector_store import query_top_k
from backend.repository.embeddings.provider import EmbeddingProvider, StubEmbeddingProvider
from backend.repository.retrieval import lexical
from backend.repository.retrieval.fusion import reciprocal_rank_fusion

RetrievalMode = Literal["lexical", "vector", "hybrid"]

_VALID_MODES = ("lexical", "vector", "hybrid")

#: Rough characters-per-token heuristic used for budget truncation, avoiding
#: a hard dependency on a specific tokenizer library for this slice.
_CHARS_PER_TOKEN_ESTIMATE = 4


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    """Optional filters narrowing a retrieval query.

    Attributes:
        path_prefix: Restrict results to chunks whose file path starts with this.
        symbol: Restrict results to chunks with this exact symbol name.
        language: Restrict results to chunks of this language. Reserved for
            forward compatibility — ``code_chunks`` does not yet carry a
            language column (E7-S1 is Python-only), so this is currently a
            no-op, mirroring :func:`backend.repository.retrieval.lexical.search`.
    """

    path_prefix: str | None = None
    symbol: str | None = None
    language: str | None = None


@dataclass(frozen=True, slots=True)
class Snippet:
    """One retrieved code chunk, with its relevance score and source attribution.

    Attributes:
        chunk_id: Identifier of the underlying ``code_chunks`` row.
        file_path: Source file the snippet was extracted from.
        symbol: Enclosing function/class name, or ``""`` for a whole-file chunk.
        start_line: 0-based inclusive start line.
        end_line: 0-based inclusive end line.
        content: The snippet's source text.
        score: Relevance score — higher is more relevant in every mode
            (fused RRF score in hybrid mode, ``ts_rank`` in lexical mode,
            ``1 - cosine distance`` in vector mode; scores are not
            comparable across modes).
        source: Which mode(s) surfaced this snippet: ``"lexical"``,
            ``"vector"``, or ``"hybrid"`` (found by both, in hybrid mode).
    """

    chunk_id: int
    file_path: str
    symbol: str
    start_line: int
    end_line: int
    content: str
    score: float
    source: str


def retrieve(
    conn: Any,
    query: str,
    *,
    tenant_id: str,
    mode: RetrievalMode = "hybrid",
    filters: RetrievalFilters | None = None,
    budget: int | None = None,
    limit: int = 20,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[Snippet]:
    """Retrieve the most relevant code snippets for *query*.

    Args:
        conn: Open psycopg connection with the ``code_chunks``/
            ``code_embeddings`` tables.
        query: Free-text (and, in vector/hybrid mode, embedded) search query.
        tenant_id: Tenant to scope the search to.
        mode: ``"lexical"`` (PostgreSQL full-text search only), ``"vector"``
            (ANN search only), or ``"hybrid"`` (both, fused via Reciprocal
            Rank Fusion).
        filters: Optional path/symbol/language filters.
        budget: Optional maximum total estimated token count across returned
            snippets; snippets are kept in relevance order until the next one
            would exceed the budget (the single best result is always kept,
            even if it alone exceeds the budget), so truncation always drops
            the least relevant results first.
        limit: Maximum number of chunk ids considered per underlying mode
            before fusion/truncation.
        embedding_provider: Provider used to embed *query* in vector/hybrid
            mode; defaults to :class:`StubEmbeddingProvider`.

    Returns:
        Snippets ordered by descending relevance, truncated to *budget*
        tokens if given.

    Raises:
        ValueError: If *mode* is not one of ``"lexical"``, ``"vector"``, or
            ``"hybrid"``.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"unknown retrieval mode: {mode!r}")
    active_filters = filters or RetrievalFilters()

    lexical_results: list[tuple[int, float]] = []
    if mode in ("lexical", "hybrid"):
        lexical_results = lexical.search(
            conn,
            query,
            tenant_id=tenant_id,
            limit=limit,
            path_prefix=active_filters.path_prefix,
            symbol=active_filters.symbol,
        )

    vector_results: list[tuple[int, float]] = []
    if mode in ("vector", "hybrid"):
        provider = embedding_provider or StubEmbeddingProvider()
        query_vector = provider.embed([query])[0]
        vector_results = query_top_k(conn, query_vector, tenant_id=tenant_id, k=limit)

    chunk_ids, scores, sources = _combine(mode, lexical_results, vector_results)
    if not chunk_ids:
        return []

    rows = _fetch_chunks(conn, chunk_ids, tenant_id, active_filters)
    snippets = [
        Snippet(
            chunk_id=row["id"],
            file_path=row["file_path"],
            symbol=row["symbol"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            content=row["content"],
            score=scores[row["id"]],
            source=sources[row["id"]],
        )
        for row in rows
        if row["id"] in scores
    ]
    snippets.sort(key=lambda snippet: -snippet.score)
    return _truncate_to_budget(snippets, budget)


def _combine(
    mode: RetrievalMode,
    lexical_results: list[tuple[int, float]],
    vector_results: list[tuple[int, float]],
) -> tuple[list[int], dict[int, float], dict[int, str]]:
    """Combine per-mode ranked results into chunk ids, scores, and source labels."""
    if mode == "lexical":
        ids = [chunk_id for chunk_id, _rank in lexical_results]
        scores = dict(lexical_results)
        sources = {chunk_id: "lexical" for chunk_id in ids}
        return ids, scores, sources

    if mode == "vector":
        ids = [chunk_id for chunk_id, _distance in vector_results]
        scores = {chunk_id: 1.0 - distance for chunk_id, distance in vector_results}
        sources = {chunk_id: "vector" for chunk_id in ids}
        return ids, scores, sources

    lexical_ids = [chunk_id for chunk_id, _rank in lexical_results]
    vector_ids = [chunk_id for chunk_id, _distance in vector_results]
    fused = reciprocal_rank_fusion([lexical_ids, vector_ids])
    ids = [chunk_id for chunk_id, _score in fused]
    scores = dict(fused)
    lexical_set, vector_set = set(lexical_ids), set(vector_ids)
    sources = {
        chunk_id: (
            "hybrid"
            if chunk_id in lexical_set and chunk_id in vector_set
            else "lexical"
            if chunk_id in lexical_set
            else "vector"
        )
        for chunk_id in ids
    }
    return ids, scores, sources


def _fetch_chunks(
    conn: Any, chunk_ids: list[int], tenant_id: str, filters: RetrievalFilters
) -> list[dict[str, Any]]:
    """Fetch chunk rows for *chunk_ids* (any order — the caller re-sorts by score)."""
    conditions = ["tenant_id = %s", "id = ANY(%s)"]
    params: list[Any] = [tenant_id, chunk_ids]
    if filters.path_prefix:
        conditions.append("file_path LIKE %s")
        params.append(f"{filters.path_prefix}%")
    if filters.symbol:
        conditions.append("symbol = %s")
        params.append(filters.symbol)
    sql = (
        "SELECT id, file_path, symbol, start_line, end_line, content FROM code_chunks "
        f"WHERE {' AND '.join(conditions)}"
    )
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": row[0],
            "file_path": row[1],
            "symbol": row[2],
            "start_line": row[3],
            "end_line": row[4],
            "content": row[5],
        }
        for row in rows
    ]


def _truncate_to_budget(snippets: list[Snippet], budget: int | None) -> list[Snippet]:
    """Keep snippets in relevance order until the next one would exceed *budget* tokens.

    Args:
        snippets: Snippets already sorted by descending relevance.
        budget: Maximum total estimated token count, or ``None`` for no limit.

    Returns:
        A prefix of *snippets* whose combined estimated token count is at
        most *budget* — except the single best snippet is always kept, even
        if its own estimated size exceeds the budget.
    """
    if budget is None:
        return snippets
    kept: list[Snippet] = []
    used = 0
    for snippet in snippets:
        estimated_tokens = max(1, len(snippet.content) // _CHARS_PER_TOKEN_ESTIMATE)
        if kept and used + estimated_tokens > budget:
            break
        kept.append(snippet)
        used += estimated_tokens
    return kept


__all__ = ["RetrievalFilters", "RetrievalMode", "Snippet", "retrieve"]
