"""Lexical retrieval over ``code_chunks`` via PostgreSQL full-text search (E7-S3-T1).

Uses ``to_tsvector('english', content)`` / ``plainto_tsquery`` and
``ts_rank``, backed by the GIN index added in
``backend/persistence/migrations/postgres_versions.py`` — no separate stored
tsvector column in this slice (an expression index is sufficient for this
story's scope; a generated stored column is a natural follow-up if lexical
query volume grows). Postgres-only, matching the rest of the E7-S1/S2 schema.
"""

from __future__ import annotations

from typing import Any


def search(
    conn: Any,
    query: str,
    *,
    tenant_id: str,
    limit: int = 10,
    path_prefix: str | None = None,
    symbol: str | None = None,
) -> list[tuple[int, float]]:
    """Return the top matching chunk ids for *query*, ranked by ``ts_rank``.

    Args:
        conn: Open psycopg connection with the ``code_chunks`` table.
        query: Free-text search query.
        tenant_id: Tenant to scope the search to.
        limit: Maximum number of results to return.
        path_prefix: Optional ``file_path`` prefix filter.
        symbol: Optional exact ``symbol`` filter.

    Returns:
        ``(chunk_id, rank)`` pairs ordered by descending ``ts_rank``; empty
        when *query* has no lexical matches.
    """
    conditions = [
        "tenant_id = %s",
        "to_tsvector('english', content) @@ plainto_tsquery('english', %s)",
    ]
    params: list[Any] = [tenant_id, query]
    if path_prefix:
        conditions.append("file_path LIKE %s")
        params.append(f"{path_prefix}%")
    if symbol:
        conditions.append("symbol = %s")
        params.append(symbol)

    rank_expr = "ts_rank(to_tsvector('english', content), plainto_tsquery('english', %s))"
    params_with_rank = [query, *params, limit]
    sql = (
        f"SELECT id, {rank_expr} AS rank FROM code_chunks "
        f"WHERE {' AND '.join(conditions)} "
        "ORDER BY rank DESC LIMIT %s"
    )
    rows = conn.execute(sql, tuple(params_with_rank)).fetchall()
    return [(row[0], row[1]) for row in rows]


__all__ = ["search"]
