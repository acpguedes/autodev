"""Pure-Python tests for Reciprocal Rank Fusion (E7-S3-T2) — no DB involved."""

from __future__ import annotations

import pytest

from backend.repository.retrieval.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion


def test_single_ranking_preserves_order() -> None:
    """Fusing a single ranking preserves its relative order."""
    fused = reciprocal_rank_fusion([["a", "b", "c"]])
    assert [item for item, _score in fused] == ["a", "b", "c"]


def test_item_appearing_in_both_rankings_outranks_single_appearance() -> None:
    """An item near the top of both rankings beats one that only appears in one."""
    lexical = ["x", "a", "b"]
    vector = ["a", "y", "z"]

    fused = reciprocal_rank_fusion([lexical, vector])

    assert fused[0][0] == "a"  # rank 2 in lexical + rank 1 in vector


def test_fused_score_matches_rrf_formula() -> None:
    """The fused score for each item matches the closed-form RRF sum."""
    lexical = ["a", "b"]
    vector = ["b", "a"]

    fused = dict(reciprocal_rank_fusion([lexical, vector], k=60))

    assert fused["a"] == pytest.approx(1 / (60 + 1) + 1 / (60 + 2))
    assert fused["b"] == pytest.approx(1 / (60 + 2) + 1 / (60 + 1))
    # Symmetric placement (rank 1 in one list, rank 2 in the other) ties.
    assert fused["a"] == pytest.approx(fused["b"])


def test_item_missing_from_a_ranking_only_scores_from_where_it_appears() -> None:
    """An item absent from one ranking contributes no term for that ranking."""
    lexical = ["a", "b"]
    vector = ["c"]

    fused = dict(reciprocal_rank_fusion([lexical, vector]))

    assert fused["a"] == pytest.approx(1 / (DEFAULT_RRF_K + 1))
    assert fused["b"] == pytest.approx(1 / (DEFAULT_RRF_K + 2))
    assert fused["c"] == pytest.approx(1 / (DEFAULT_RRF_K + 1))


def test_weights_scale_each_ranking_contribution() -> None:
    """A higher weight on one ranking increases that ranking's influence on the fused score."""
    lexical = ["a"]
    vector = ["b"]

    fused = dict(reciprocal_rank_fusion([lexical, vector], weights=[2.0, 1.0]))

    assert fused["a"] == pytest.approx(2.0 / (DEFAULT_RRF_K + 1))
    assert fused["b"] == pytest.approx(1.0 / (DEFAULT_RRF_K + 1))
    assert fused["a"] > fused["b"]


def test_empty_rankings_produce_empty_result() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)


def test_rejects_mismatched_weights_length() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"], ["b"]], weights=[1.0])


def test_ties_broken_by_first_seen_order() -> None:
    """Items with an identical fused score keep the order they were first seen in."""
    fused = reciprocal_rank_fusion([["a"], ["b"]])  # both rank 1 in their own list -> tied score
    assert [item for item, _score in fused] == ["a", "b"]
