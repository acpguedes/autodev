"""Tests for backend.repository.retrieval.retriever: mode dispatch, fusion, and budget truncation.

Lexical/vector backends and chunk fetching are monkeypatched to fixture
data — no database involved — so these tests exercise the retriever's real
combination/truncation logic in isolation.
"""

from __future__ import annotations

import pytest

from backend.repository.retrieval import retriever as retriever_module
from backend.repository.retrieval.retriever import RetrievalFilters, retrieve

_ROWS = {
    1: {"id": 1, "file_path": "a.py", "symbol": "foo", "start_line": 0, "end_line": 3, "content": "x" * 40},
    2: {"id": 2, "file_path": "b.py", "symbol": "bar", "start_line": 5, "end_line": 8, "content": "y" * 40},
    3: {"id": 3, "file_path": "c.py", "symbol": "baz", "start_line": 1, "end_line": 2, "content": "z" * 40},
}


def _patch_backends(monkeypatch, lexical_results, vector_results) -> None:
    """Monkeypatch the retriever's lexical/vector/fetch dependencies to fixture data."""
    monkeypatch.setattr(retriever_module.lexical, "search", lambda *a, **k: lexical_results)
    monkeypatch.setattr(retriever_module, "query_top_k", lambda *a, **k: vector_results)
    monkeypatch.setattr(
        retriever_module,
        "_fetch_chunks",
        lambda conn, chunk_ids, tenant_id, filters: [_ROWS[i] for i in chunk_ids if i in _ROWS],
    )


def test_lexical_mode_only_uses_lexical_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_backends(monkeypatch, [(1, 0.9), (2, 0.5)], [(3, 0.1)])

    snippets = retrieve(object(), "add", tenant_id="default", mode="lexical")

    assert [snippet.chunk_id for snippet in snippets] == [1, 2]
    assert all(snippet.source == "lexical" for snippet in snippets)


def test_vector_mode_only_uses_vector_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_backends(monkeypatch, [(1, 0.9)], [(3, 0.1), (2, 0.3)])

    snippets = retrieve(object(), "add", tenant_id="default", mode="vector")

    assert {snippet.chunk_id for snippet in snippets} == {2, 3}
    assert all(snippet.source == "vector" for snippet in snippets)
    assert snippets[0].chunk_id == 3  # lower distance -> higher score -> ranked first


def test_hybrid_mode_fuses_both_and_labels_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_backends(monkeypatch, [(1, 0.9), (2, 0.4)], [(2, 0.1), (3, 0.2)])

    snippets = retrieve(object(), "add", tenant_id="default", mode="hybrid")

    by_id = {snippet.chunk_id: snippet for snippet in snippets}
    assert by_id[2].source == "hybrid"
    assert by_id[1].source == "lexical"
    assert by_id[3].source == "vector"


def test_invalid_mode_raises_value_error() -> None:
    with pytest.raises(ValueError):
        retrieve(object(), "add", tenant_id="default", mode="bogus")  # type: ignore[arg-type]


def test_filters_are_forwarded_to_lexical_search(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_search(conn, query, *, tenant_id, limit, path_prefix, symbol):  # noqa: ANN001, ARG001
        captured["path_prefix"] = path_prefix
        captured["symbol"] = symbol
        return []

    monkeypatch.setattr(retriever_module.lexical, "search", fake_search)
    monkeypatch.setattr(retriever_module, "query_top_k", lambda *a, **k: [])

    retrieve(
        object(),
        "add",
        tenant_id="default",
        mode="lexical",
        filters=RetrievalFilters(path_prefix="pkg/", symbol="foo"),
    )

    assert captured == {"path_prefix": "pkg/", "symbol": "foo"}


def test_budget_truncates_least_relevant_first(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_backends(monkeypatch, [(1, 0.9), (2, 0.5), (3, 0.1)], [])

    full = retrieve(object(), "add", tenant_id="default", mode="lexical")
    assert len(full) == 3

    # Each row's content is 40 chars -> ~10 estimated tokens; a budget of 15
    # fits the top result plus a sliver, so only the best result survives.
    budgeted = retrieve(object(), "add", tenant_id="default", mode="lexical", budget=15)

    assert 0 < len(budgeted) < len(full)
    assert [snippet.chunk_id for snippet in budgeted] == [snippet.chunk_id for snippet in full[: len(budgeted)]]


def test_budget_always_keeps_at_least_the_top_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_backends(monkeypatch, [(1, 0.9)], [])

    snippets = retrieve(object(), "add", tenant_id="default", mode="lexical", budget=1)

    assert len(snippets) == 1


def test_no_results_from_either_backend_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_backends(monkeypatch, [], [])

    assert retrieve(object(), "add", tenant_id="default", mode="hybrid") == []
