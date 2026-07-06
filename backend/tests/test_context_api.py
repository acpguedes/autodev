"""Integration tests for GET /v2/context/retrieve (E7-S3).

The retriever's lexical/vector backends and chunk fetch are monkeypatched to
fixture data (no live PostgreSQL/pgvector) — these tests assert the endpoint
wires request params through to the retriever correctly, serializes results,
and enforces the token budget end to end.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.routers import context as context_router
from backend.repository.retrieval import retriever as retriever_module

client = TestClient(app)

_ROWS = {
    1: {"id": 1, "file_path": "pkg/a.py", "symbol": "add", "start_line": 0, "end_line": 2, "content": "a" * 40},
    2: {"id": 2, "file_path": "pkg/b.py", "symbol": "sub", "start_line": 4, "end_line": 6, "content": "b" * 40},
}


class _DummyConn:
    """Minimal context-manager stand-in for a connection; never queried directly (backends are mocked)."""

    def __enter__(self) -> "_DummyConn":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _fake_store(database_url: str = "postgresql://fake/db") -> SimpleNamespace:
    """Build a minimal store double exposing just ``database_url`` and ``connect()``."""
    return SimpleNamespace(database_url=database_url, connect=lambda: _DummyConn())


def _patch_backends(monkeypatch: pytest.MonkeyPatch, lexical_results, vector_results) -> None:
    """Monkeypatch the retriever's lexical/vector/fetch dependencies to fixture data."""
    monkeypatch.setattr(retriever_module.lexical, "search", lambda *a, **k: lexical_results)
    monkeypatch.setattr(retriever_module, "query_top_k", lambda *a, **k: vector_results)
    monkeypatch.setattr(
        retriever_module,
        "_fetch_chunks",
        lambda conn, chunk_ids, tenant_id, filters: [_ROWS[i] for i in chunk_ids if i in _ROWS],
    )


def test_retrieve_context_returns_ranked_snippets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_router, "get_store", lambda: _fake_store())
    _patch_backends(monkeypatch, lexical_results=[(1, 0.9), (2, 0.3)], vector_results=[])

    resp = client.get("/v2/context/retrieve", params={"query": "add", "mode": "lexical"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "add"
    assert body["mode"] == "lexical"
    assert [r["chunkId"] for r in body["results"]] == [1, 2]
    assert body["results"][0]["filePath"] == "pkg/a.py"
    assert body["results"][0]["source"] == "lexical"
    assert body["results"][0]["score"] == pytest.approx(0.9)


def test_retrieve_context_respects_token_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_router, "get_store", lambda: _fake_store())
    _patch_backends(monkeypatch, lexical_results=[(1, 0.9), (2, 0.3)], vector_results=[])

    full = client.get("/v2/context/retrieve", params={"query": "add", "mode": "lexical"}).json()
    budgeted = client.get(
        "/v2/context/retrieve", params={"query": "add", "mode": "lexical", "budget": 5}
    ).json()

    assert len(budgeted["results"]) < len(full["results"])
    assert budgeted["results"][0]["chunkId"] == full["results"][0]["chunkId"]


def test_retrieve_context_forwards_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_router, "get_store", lambda: _fake_store())
    captured: dict[str, object] = {}

    def fake_search(conn, query, *, tenant_id, limit, path_prefix, symbol):  # noqa: ANN001, ARG001
        captured["path_prefix"] = path_prefix
        captured["symbol"] = symbol
        return []

    monkeypatch.setattr(retriever_module.lexical, "search", fake_search)
    monkeypatch.setattr(retriever_module, "query_top_k", lambda *a, **k: [])

    resp = client.get(
        "/v2/context/retrieve",
        params={"query": "add", "mode": "lexical", "path_prefix": "pkg/", "symbol": "add"},
    )

    assert resp.status_code == 200
    assert captured == {"path_prefix": "pkg/", "symbol": "add"}


def test_retrieve_context_rejects_invalid_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_router, "get_store", lambda: _fake_store())

    resp = client.get("/v2/context/retrieve", params={"query": "add", "mode": "bogus"})

    assert resp.status_code == 422


def test_retrieve_context_returns_501_for_non_postgres_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_router, "get_store", lambda: _fake_store("sqlite:///./local.db"))

    resp = client.get("/v2/context/retrieve", params={"query": "add"})

    assert resp.status_code == 501


def test_retrieve_context_requires_non_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_router, "get_store", lambda: _fake_store())

    resp = client.get("/v2/context/retrieve", params={"query": ""})

    assert resp.status_code == 422
