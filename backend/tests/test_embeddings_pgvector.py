"""Tests for the E7-S2 embedding provider and pgvector-backed store (ADR-011)."""

from __future__ import annotations

import math
import sys
from types import SimpleNamespace

import pytest

from backend.persistence.postgres_adapter import PostgresStore
from backend.repository.chunking import chunk_source
from backend.repository.embeddings.pgvector_store import query_top_k, upsert_embeddings
from backend.repository.embeddings.provider import DEFAULT_EMBEDDING_DIMENSION, StubEmbeddingProvider

_PY_SAMPLE = """\
def add(a, b):
    return a + b


class Greeter:
    def greet(self, name):
        return f"hello {name}"
"""


# ---------------------------------------------------------------------------
# StubEmbeddingProvider
# ---------------------------------------------------------------------------


def test_stub_provider_embeds_chunks_from_unit1_fixture() -> None:
    """StubEmbeddingProvider produces one L2-normalized vector per chunk from a real chunk_source() run."""
    chunks = chunk_source("pkg/mod_a.py", _PY_SAMPLE, "python", overlap_lines=0)
    provider = StubEmbeddingProvider()

    vectors = provider.embed([chunk.content for chunk in chunks])

    assert len(vectors) == len(chunks)
    for vector in vectors:
        assert len(vector) == provider.dimension == DEFAULT_EMBEDDING_DIMENSION
        norm = math.sqrt(sum(value * value for value in vector))
        assert math.isclose(norm, 1.0, abs_tol=1e-6)


def test_stub_provider_is_deterministic() -> None:
    """The same text always yields the same vector."""
    provider = StubEmbeddingProvider(dimension=16)
    first = provider.embed(["def add(a, b): return a + b"])
    second = provider.embed(["def add(a, b): return a + b"])
    assert first == second


def test_stub_provider_different_texts_yield_different_vectors() -> None:
    """Distinct inputs produce distinct vectors (not a constant/degenerate embedding)."""
    provider = StubEmbeddingProvider(dimension=16)
    vectors = provider.embed(["def add(): pass", "class Foo: pass"])
    assert vectors[0] != vectors[1]


def test_stub_provider_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError):
        StubEmbeddingProvider(dimension=0)


# ---------------------------------------------------------------------------
# PostgresStore DDL: extension, table, HNSW index, RLS (FakeConnection mock)
# ---------------------------------------------------------------------------


class FakeCursor:
    """In-memory stand-in for a psycopg cursor, recording executed SQL on its connection."""

    def __init__(self, conn: "FakeConnection") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> "FakeCursor":
        self.conn.executed.append((sql, params))
        return self

    def fetchone(self) -> object:
        return None

    def fetchall(self) -> list[object]:
        return []


class FakeConnection:
    """In-memory stand-in for a psycopg connection, used to assert on executed DDL."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []
        self.commits = 0

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def execute(self, sql: str, params: object = None) -> FakeCursor:
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self) -> None:
        self.commits += 1


def _install_fake_psycopg(monkeypatch: pytest.MonkeyPatch) -> list[FakeConnection]:
    """Patch ``sys.modules['psycopg']`` with a fake module recording connections made."""
    connections: list[FakeConnection] = []

    def connect(database_url: str) -> FakeConnection:
        assert database_url.startswith("postgresql://")
        conn = FakeConnection()
        connections.append(conn)
        return conn

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    return connections


def test_postgres_store_creates_vector_extension_table_and_hnsw_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing a PostgresStore issues the pgvector extension/table/index/RLS DDL."""
    connections = _install_fake_psycopg(monkeypatch)

    PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    executed_sql = "\n".join(sql for sql, _params in connections[0].executed)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS code_embeddings" in executed_sql
    assert "REFERENCES code_chunks(id)" in executed_sql
    assert "USING hnsw" in executed_sql
    assert "vector_cosine_ops" in executed_sql
    assert "ENABLE ROW LEVEL SECURITY" in executed_sql
    assert "CREATE POLICY code_embeddings_tenant_isolation" in executed_sql


# ---------------------------------------------------------------------------
# upsert_embeddings(): dedup-upsert shape + skip-unchanged-hash behavior
# ---------------------------------------------------------------------------


class _FakeEmbeddingsCursor:
    """Cursor returned by :class:`_FakeEmbeddingsConnection`, wrapping a fixed row list."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows

    def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None


class _FakeEmbeddingsConnection:
    """Minimal stateful fake Postgres connection for ``upsert_embeddings``/``query_top_k``.

    Tracks ``(tenant_id, chunk_id) -> content_hash`` in memory and recognizes
    exactly the query shapes ``pgvector_store.py`` issues — not a general SQL
    engine, but enough to exercise the dedup-by-hash contract without a live
    PostgreSQL/pgvector instance.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []
        self._rows: dict[tuple[str, int], str] = {}

    def execute(self, sql: str, params: tuple = ()) -> _FakeEmbeddingsCursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT chunk_id, content_hash FROM code_embeddings"):
            tenant_id, chunk_ids = params
            rows = [
                (chunk_id, content_hash)
                for (tenant, chunk_id), content_hash in self._rows.items()
                if tenant == tenant_id and chunk_id in chunk_ids
            ]
            return _FakeEmbeddingsCursor(rows)
        if normalized.startswith("INSERT INTO code_embeddings"):
            tenant_id, chunk_id, content_hash, _embedding, _model = params
            self._rows[(tenant_id, chunk_id)] = content_hash
            return _FakeEmbeddingsCursor([])
        return _FakeEmbeddingsCursor([])

    def commit(self) -> None:
        return None


def test_upsert_embeddings_issues_dedup_upsert_statement() -> None:
    """upsert_embeddings() issues an INSERT ... ON CONFLICT dedup-upsert statement."""
    conn = _FakeEmbeddingsConnection()
    provider = StubEmbeddingProvider(dimension=8)
    chunk_rows = [(1, "def add(a, b): return a + b", "hash-a")]

    written = upsert_embeddings(conn, chunk_rows, provider, tenant_id="default")

    assert written == 1
    insert_sql = next(sql for sql, _params in conn.executed if "INSERT INTO code_embeddings" in sql)
    assert "ON CONFLICT (tenant_id, chunk_id) DO UPDATE" in insert_sql
    assert "::vector" in insert_sql


def test_upsert_embeddings_skips_unchanged_hash_on_second_run() -> None:
    """A second upsert with identical content hashes re-embeds and rewrites nothing."""
    conn = _FakeEmbeddingsConnection()
    provider = StubEmbeddingProvider(dimension=8)
    chunk_rows = [
        (1, "def add(a, b): return a + b", "hash-a"),
        (2, "class Foo: pass", "hash-b"),
    ]

    first_written = upsert_embeddings(conn, chunk_rows, provider, tenant_id="default")
    assert first_written == 2

    second_written = upsert_embeddings(conn, chunk_rows, provider, tenant_id="default")
    assert second_written == 0


def test_upsert_embeddings_only_re_embeds_the_changed_chunk() -> None:
    """Changing one chunk's hash re-embeds only that chunk, leaving the other untouched."""
    conn = _FakeEmbeddingsConnection()
    provider = StubEmbeddingProvider(dimension=8)
    chunk_rows = [
        (1, "def add(a, b): return a + b", "hash-a"),
        (2, "class Foo: pass", "hash-b"),
    ]
    upsert_embeddings(conn, chunk_rows, provider, tenant_id="default")

    changed_rows = [chunk_rows[0], (2, "class Foo: pass", "hash-b-changed")]
    written = upsert_embeddings(conn, changed_rows, provider, tenant_id="default")

    assert written == 1
    assert conn._rows[("default", 2)] == "hash-b-changed"


def test_upsert_embeddings_empty_input_is_a_noop() -> None:
    """Calling upsert_embeddings with no chunk rows writes nothing and issues no queries."""
    conn = _FakeEmbeddingsConnection()
    written = upsert_embeddings(conn, [], StubEmbeddingProvider(), tenant_id="default")
    assert written == 0
    assert conn.executed == []


def test_query_top_k_issues_ann_query_scoped_to_tenant() -> None:
    """query_top_k() issues a tenant-scoped nearest-neighbor query using the <=> operator."""
    conn = _FakeEmbeddingsConnection()
    provider = StubEmbeddingProvider(dimension=8)
    vector = provider.embed(["def add(a, b): return a + b"])[0]

    results = query_top_k(conn, vector, tenant_id="acme", k=5)

    assert results == []  # no rows in the fake backing store
    query_sql, raw_params = conn.executed[-1]
    assert "<=>" in query_sql
    assert "WHERE tenant_id = %s" in query_sql
    assert isinstance(raw_params, tuple)
    _vector_arg, tenant_arg, limit_arg = raw_params
    assert tenant_arg == "acme"
    assert limit_arg == 5
