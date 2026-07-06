"""Reciprocal Rank Fusion for combining ranked result lists (E7-S3-T2).

Pure-Python and DB-free by design: it operates on ranked id sequences (e.g.
lexical chunk ids ranked by ``ts_rank`` and vector chunk ids ranked by cosine
distance) rather than on raw scores, which is exactly why it composes rankers
whose scores live on incompatible scales without any score normalization
step.
"""

from __future__ import annotations

from typing import Hashable, Sequence, TypeVar

T = TypeVar("T", bound=Hashable)

#: Standard RRF smoothing constant (Cormack, Clarke & Buettcher, 2009).
DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[T]],
    *,
    k: int = DEFAULT_RRF_K,
    weights: Sequence[float] | None = None,
) -> list[tuple[T, float]]:
    """Fuse multiple ranked lists of the same item type into one ranking.

    Each item's fused score is the (optionally weighted) sum, across every
    ranking it appears in, of ``1 / (k + rank)``, where ``rank`` is its
    1-based position in that ranking. An item absent from a ranking simply
    contributes no term for it.

    Args:
        rankings: One ranked sequence of items per retrieval mode (e.g.
            ``[lexical_chunk_ids, vector_chunk_ids]``), best-first.
        k: Smoothing constant; higher values reduce the influence of an
            item's exact rank position. Defaults to the standard RRF value.
        weights: Optional per-ranking weight, same length as *rankings*;
            defaults to equal (1.0) weight for every ranking.

    Returns:
        ``(item, fused_score)`` pairs sorted by descending fused score, ties
        broken by the order each item was first seen across *rankings*.

    Raises:
        ValueError: If *k* is not positive, or *weights* is provided with a
            length that does not match *rankings*.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("weights must have the same length as rankings")
    active_weights = weights if weights is not None else [1.0] * len(rankings)

    scores: dict[T, float] = {}
    first_seen_order: dict[T, int] = {}
    next_order = 0
    for ranking, weight in zip(rankings, active_weights):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + weight * (1.0 / (k + rank))
            if item not in first_seen_order:
                first_seen_order[item] = next_order
                next_order += 1

    return sorted(scores.items(), key=lambda pair: (-pair[1], first_seen_order[pair[0]]))


__all__ = ["DEFAULT_RRF_K", "reciprocal_rank_fusion"]
