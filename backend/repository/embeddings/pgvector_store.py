"""pgvector-backed vector store for code chunk embeddings (E7-S2-T2/T3).

Requires PostgreSQL with the ``vector`` extension and the ``code_embeddings``
table (created by the migration in
``backend/persistence/migrations/postgres_versions.py``) — there is no
SQLite equivalent; local-first (SQLite) deployments can still run an
:class:`~backend.repository.embeddings.provider.EmbeddingProvider` but do not
persist vectors (see ADR-011).

The ``pgvector`` Python package is an *optional* dependency, imported lazily
exactly like ``tree_sitter``
(``backend/repository/providers/treesitter_provider.py``): when installed, it
registers a psycopg type adapter so a plain ``list[float]`` can be bound
directly as a query parameter; when absent, vectors are formatted as a
bracketed text literal (``'[0.1,0.2,...]'::vector``) instead — either path
produces the same SQL semantics against PostgreSQL.
"""

from __future__ import annotations

from typing import Any, Sequence

from backend.repository.embeddings.provider import EmbeddingProvider

try:
    import pgvector.psycopg  # type: ignore[import-untyped]

    _PGVECTOR_PACKAGE_AVAILABLE = True
except ImportError:
    _PGVECTOR_PACKAGE_AVAILABLE = False


def register_vector_adapter(conn: Any) -> bool:
    """Register the ``pgvector`` psycopg type adapter on *conn*, if possible.

    Safe to call unconditionally and never raises: registration requires a
    live catalog lookup of the ``vector`` type (``TypeInfo.fetch``), which
    only succeeds against a real psycopg connection where the ``vector``
    extension is already created — it fails on a connection mock (as used in
    this module's tests) or if the extension isn't loaded yet. Any failure
    (including the optional ``pgvector`` package not being installed at all)
    is treated as "use the string-literal fallback" in :func:`_vector_param`
    rather than as an error.

    Args:
        conn: Open psycopg connection.

    Returns:
        ``True`` if the adapter was registered on *conn* and callers should
        bind vectors as plain ``list`` objects; ``False`` if callers should
        use the pgvector text-literal fallback instead.
    """
    if not _PGVECTOR_PACKAGE_AVAILABLE:
        return False
    try:
        pgvector.psycopg.register_vector(conn)
        return True
    except Exception:
        return False


def _vector_param(vector: Sequence[float], *, adapter_active: bool) -> Any:
    """Return *vector* in whatever form the current connection's adapter expects.

    Args:
        vector: Embedding vector to bind as a query parameter.
        adapter_active: Whether :func:`register_vector_adapter` succeeded on
            this connection.

    Returns:
        The vector as a plain ``list`` (for binding via the registered
        ``pgvector`` adapter) when *adapter_active*, otherwise a pgvector
        text literal string (``'[0.1,0.2,...]'``) for a ``%s::vector`` cast
        — valid PostgreSQL syntax either way.
    """
    if adapter_active:
        return list(vector)
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def upsert_embeddings(
    conn: Any,
    chunk_rows: Sequence[tuple[int, str, str]],
    provider: EmbeddingProvider,
    *,
    tenant_id: str,
    model: str = "stub",
) -> int:
    """Embed and upsert vectors for chunks whose content hash has changed.

    Chunks whose ``content_hash`` already matches the stored embedding row
    are skipped entirely — neither re-embedded nor rewritten — so a
    reindex that touched only some chunks does not re-run the (potentially
    expensive/rate-limited) embedding call for everything else.

    Args:
        conn: Open psycopg connection with the ``code_embeddings`` table.
        chunk_rows: ``(chunk_id, content, content_hash)`` triples, typically
            read from ``code_chunks`` for a tenant/file.
        provider: Embedding provider to run over any new/changed content.
        tenant_id: Tenant to scope embedding rows to.
        model: Label recorded on each row identifying the provider/model used.

    Returns:
        Number of rows inserted or updated.
    """
    if not chunk_rows:
        return 0
    adapter_active = register_vector_adapter(conn)
    chunk_ids = [row[0] for row in chunk_rows]
    existing = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT chunk_id, content_hash FROM code_embeddings "
            "WHERE tenant_id = %s AND chunk_id = ANY(%s)",
            (tenant_id, chunk_ids),
        ).fetchall()
    }
    to_embed = [row for row in chunk_rows if existing.get(row[0]) != row[2]]
    if not to_embed:
        return 0

    vectors = provider.embed([content for _chunk_id, content, _hash in to_embed])
    written = 0
    for (chunk_id, _content, content_hash), vector in zip(to_embed, vectors):
        conn.execute(
            """
            INSERT INTO code_embeddings (tenant_id, chunk_id, content_hash, embedding, model)
            VALUES (%s, %s, %s, %s::vector, %s)
            ON CONFLICT (tenant_id, chunk_id) DO UPDATE SET
                content_hash = excluded.content_hash,
                embedding = excluded.embedding,
                model = excluded.model,
                created_at = CURRENT_TIMESTAMP
            """,
            (tenant_id, chunk_id, content_hash, _vector_param(vector, adapter_active=adapter_active), model),
        )
        written += 1
    conn.commit()
    return written


def query_top_k(
    conn: Any,
    query_vector: Sequence[float],
    *,
    tenant_id: str,
    k: int = 10,
) -> list[tuple[int, float]]:
    """Return the *k* nearest chunk ids to *query_vector*, scoped to a tenant.

    Args:
        conn: Open psycopg connection with the ``code_embeddings`` table.
        query_vector: Embedding to search for nearest neighbors of.
        tenant_id: Tenant to scope the ANN search to (also enforced by RLS
            when the caller has set the tenant session variable via
            :func:`backend.persistence.tenancy.set_postgres_tenant`).
        k: Maximum number of results to return.

    Returns:
        ``(chunk_id, distance)`` pairs ordered by ascending cosine distance
        (nearest first) — the HNSW index on ``code_embeddings.embedding``
        makes this an approximate-nearest-neighbor query.
    """
    adapter_active = register_vector_adapter(conn)
    rows = conn.execute(
        """
        SELECT chunk_id, embedding <=> %s::vector AS distance
        FROM code_embeddings
        WHERE tenant_id = %s
        ORDER BY distance ASC
        LIMIT %s
        """,
        (_vector_param(query_vector, adapter_active=adapter_active), tenant_id, k),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


__all__ = ["query_top_k", "register_vector_adapter", "upsert_embeddings"]
