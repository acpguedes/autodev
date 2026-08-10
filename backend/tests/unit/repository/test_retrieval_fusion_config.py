"""Tests for caller-configurable Reciprocal Rank Fusion (E7-S3 DoD).

``fusion.reciprocal_rank_fusion`` always accepted ``k`` and ``weights``, but
``retrieve()`` neither accepted nor forwarded them, so fusion was
unconfigurable from every caller including the HTTP surface. These tests pin
the plumbing that closes that gap.

Lexical/vector backends and chunk fetching are monkeypatched to fixture data,
so no database is involved.
"""

from __future__ import annotations

import pytest

from backend.repository.retrieval import retriever as retriever_module
from backend.repository.retrieval.fusion import DEFAULT_RRF_K
from backend.repository.retrieval.retriever import retrieve

_ROWS = {
    1: {"id": 1, "file_path": "a.py", "symbol": "foo", "start_line": 0, "end_line": 3, "content": "x" * 40},
    2: {"id": 2, "file_path": "b.py", "symbol": "bar", "start_line": 5, "end_line": 8, "content": "y" * 40},
    3: {"id": 3, "file_path": "c.py", "symbol": "baz", "start_line": 1, "end_line": 2, "content": "z" * 40},
}


def _patch_backends(
    monkeypatch: pytest.MonkeyPatch,
    lexical_results: list[tuple[int, float]],
    vector_results: list[tuple[int, float]],
) -> None:
    """Monkeypatch the retriever's lexical/vector/fetch dependencies.

    Args:
        monkeypatch: Pytest's patcher.
        lexical_results: Fixture ``(chunk_id, rank)`` pairs for lexical search.
        vector_results: Fixture ``(chunk_id, distance)`` pairs for vector search.
    """
    monkeypatch.setattr(retriever_module.lexical, "search", lambda *a, **k: lexical_results)
    monkeypatch.setattr(retriever_module, "query_top_k", lambda *a, **k: vector_results)
    monkeypatch.setattr(
        retriever_module,
        "_fetch_chunks",
        lambda conn, chunk_ids, tenant_id, filters: [_ROWS[i] for i in chunk_ids if i in _ROWS],
    )


def test_weights_change_the_fused_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Favoring one ranker must reorder results that the other ranked first."""
    _patch_backends(monkeypatch, [(1, 0.9), (2, 0.4)], [(2, 0.1), (1, 0.2)])

    lexical_first = retrieve(
        object(), "add", tenant_id="default", mode="hybrid", fusion_weights=(10.0, 1.0)
    )
    vector_first = retrieve(
        object(), "add", tenant_id="default", mode="hybrid", fusion_weights=(1.0, 10.0)
    )

    assert lexical_first[0].chunk_id == 1
    assert vector_first[0].chunk_id == 2


def test_zero_weight_removes_a_ranker_from_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero-weighted ranker still contributes candidates, but no score."""
    _patch_backends(monkeypatch, [(1, 0.9)], [(2, 0.1)])

    snippets = retrieve(
        object(), "add", tenant_id="default", mode="hybrid", fusion_weights=(0.0, 1.0)
    )

    by_id = {snippet.chunk_id: snippet for snippet in snippets}
    assert by_id[1].score == 0.0
    assert by_id[2].score > 0.0


def test_k_is_forwarded_and_changes_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    """A larger smoothing constant flattens scores toward zero."""
    _patch_backends(monkeypatch, [(1, 0.9), (2, 0.4)], [])

    default_k = retrieve(object(), "add", tenant_id="default", mode="hybrid")
    large_k = retrieve(object(), "add", tenant_id="default", mode="hybrid", fusion_k=10_000)

    assert default_k[0].score > large_k[0].score
    assert [s.chunk_id for s in default_k] == [s.chunk_id for s in large_k]


def test_invalid_k_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-positive smoothing constant raises rather than dividing by zero."""
    _patch_backends(monkeypatch, [(1, 0.9)], [(2, 0.1)])

    with pytest.raises(ValueError):
        retrieve(object(), "add", tenant_id="default", mode="hybrid", fusion_k=0)


def test_mismatched_weights_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Weights must name exactly the two rankings hybrid mode fuses."""
    _patch_backends(monkeypatch, [(1, 0.9)], [(2, 0.1)])

    with pytest.raises(ValueError):
        retrieve(
            object(), "add", tenant_id="default", mode="hybrid", fusion_weights=(1.0, 1.0, 1.0)
        )


def test_fusion_settings_are_ignored_outside_hybrid_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-ranker modes never fuse, so an invalid constant cannot bite them."""
    _patch_backends(monkeypatch, [(1, 0.9)], [(2, 0.1)])

    lexical = retrieve(object(), "add", tenant_id="default", mode="lexical", fusion_k=0)
    vector = retrieve(object(), "add", tenant_id="default", mode="vector", fusion_k=0)

    assert [snippet.chunk_id for snippet in lexical] == [1]
    assert [snippet.chunk_id for snippet in vector] == [2]


def test_default_matches_the_documented_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Omitting the constant must equal passing the documented default."""
    _patch_backends(monkeypatch, [(1, 0.9), (2, 0.4)], [(2, 0.1)])

    implicit = retrieve(object(), "add", tenant_id="default", mode="hybrid")
    explicit = retrieve(
        object(), "add", tenant_id="default", mode="hybrid", fusion_k=DEFAULT_RRF_K
    )

    assert [(s.chunk_id, s.score) for s in implicit] == [
        (s.chunk_id, s.score) for s in explicit
    ]
