"""Context & RAG retrieval API (E7-S3-T3/T4).

API-first (reference doc §2.13): ``GET /v2/context/retrieve`` is the single
entry point Web UI/CLI/MCP/agents use for hybrid code retrieval — no
internal caller reaches into the retriever or the durable store directly.

The router is auto-discovered by
:func:`backend.api.routers.include_all_routers` via the standard ``router``
attribute — no changes to ``main.py`` are required (matching the convention
in ``backend/api/routers/repo_symbols.py``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.persistence.database import get_store
from backend.persistence.tenancy import DEFAULT_TENANT_ID
from backend.repository.retrieval.retriever import RetrievalFilters, retrieve

router = APIRouter(prefix="/v2/context", tags=["context"])


def get_durable_store() -> Any:
    """Build the durable-store dependency for request handlers.

    Returns:
        The process-wide cached store (see
        :func:`backend.persistence.database.get_store`).
    """
    return get_store()


@router.get("/retrieve")
def retrieve_context(
    query: str = Query(..., min_length=1, description="Free-text/semantic search query"),
    mode: str = Query(default="hybrid", description="One of: lexical, vector, hybrid"),
    tenant_id: str = Query(default=DEFAULT_TENANT_ID),
    path_prefix: str | None = Query(default=None, description="Restrict results to this file path prefix"),
    symbol: str | None = Query(default=None, description="Restrict results to this exact symbol name"),
    budget: int | None = Query(default=None, ge=1, description="Max total estimated tokens across results"),
    limit: int = Query(default=20, ge=1, le=100, description="Max chunk ids considered per retrieval mode"),
    store: Any = Depends(get_durable_store),
) -> dict[str, Any]:
    """Retrieve the most relevant code snippets for *query* via hybrid retrieval.

    Args:
        query: Free-text (and, in vector/hybrid mode, embedded) search query.
        mode: ``"lexical"``, ``"vector"``, or ``"hybrid"`` (default).
        tenant_id: Tenant to scope the search to.
        path_prefix: Optional file path prefix filter.
        symbol: Optional exact symbol name filter.
        budget: Optional maximum total estimated token count across results;
            results are truncated in relevance order (least relevant
            dropped first) rather than arbitrarily cut off.
        limit: Maximum number of chunk ids considered per underlying
            retrieval mode before fusion/truncation.
        store: Durable store dependency.

    Returns:
        ``{"query", "mode", "results": [{"chunkId", "filePath", "symbol",
        "startLine", "endLine", "content", "score", "source"}, ...]}``.

    Raises:
        HTTPException: 422 for an unrecognized *mode*; 501 when the active
            store is not PostgreSQL (hybrid retrieval requires pgvector and
            full-text search, both Postgres-only — see ADR-011).
    """
    if mode not in ("lexical", "vector", "hybrid"):
        raise HTTPException(status_code=422, detail=f"invalid mode: {mode!r}")
    _require_postgres_store(store)

    filters = RetrievalFilters(path_prefix=path_prefix, symbol=symbol)
    with store.connect() as conn:
        snippets = retrieve(
            conn,
            query,
            tenant_id=tenant_id,
            mode=mode,  # type: ignore[arg-type]
            filters=filters,
            budget=budget,
            limit=limit,
        )

    return {
        "query": query,
        "mode": mode,
        "results": [
            {
                "chunkId": snippet.chunk_id,
                "filePath": snippet.file_path,
                "symbol": snippet.symbol,
                "startLine": snippet.start_line,
                "endLine": snippet.end_line,
                "content": snippet.content,
                "score": snippet.score,
                "source": snippet.source,
            }
            for snippet in snippets
        ],
    }


def _require_postgres_store(store: Any) -> None:
    """Raise a clear 501 if *store* is not PostgreSQL-backed.

    Args:
        store: Durable store instance to check.

    Raises:
        HTTPException: 501 if *store*'s ``database_url`` is not a
            ``postgresql://``/``postgres://`` URL.
    """
    url = str(getattr(store, "database_url", ""))
    if not url.startswith(("postgresql://", "postgres://")):
        raise HTTPException(
            status_code=501,
            detail=(
                "Hybrid retrieval requires PostgreSQL with the pgvector extension; "
                "the active store is not PostgreSQL-backed."
            ),
        )


__all__ = ["get_durable_store", "retrieve_context", "router"]
