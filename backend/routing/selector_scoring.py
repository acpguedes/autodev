"""``score-weighted`` selector stage: blend a ScoreSnapshot into ranking (E5-S4).

Split out of :mod:`backend.routing.selector` to keep both modules under the
repository's file-size guideline — mirrors the
:mod:`backend.routing.policy`/:mod:`backend.routing.selector_policy_parsing`
split. This module has no dependency on :mod:`backend.routing.selector` (a
one-directional dependency the other way — ``selector.py`` imports
:func:`apply_score_weighted` from here — so there is no import cycle).

See :mod:`backend.routing.selector`'s module docstring for the pipeline this
stage participates in, and :mod:`backend.routing.feedback` for how a
:class:`~backend.routing.contract.ScoreSnapshot` is published and promoted in
the first place.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from backend.agents.registry_v2 import AgentRef
from backend.routing.contract import AgentScoreAggregate, ScoreSnapshot
from backend.routing.policy import SelectorScoreWeightedStageSpec

#: Objective the final deterministic sort applies when this stage actually
#: blended a snapshot into candidates' ``.score`` — reuses the existing
#: ``maximize_quality`` objective (``-candidate.score`` ascending), since
#: ``AgentRef.score`` is already documented as a general-purpose "ranking
#: score used when searching by capability" (E5-S4).
SCORE_WEIGHTED_OBJECTIVE = "maximize_quality"


def apply_score_weighted(
    candidates: list[AgentRef],
    spec: SelectorScoreWeightedStageSpec,
    scores: ScoreSnapshot | None,
) -> tuple[list[AgentRef], bool]:
    """Apply the ``score-weighted`` stage: blend a snapshot into candidate ranking (E5-S4).

    A documented no-op passthrough when either no snapshot is supplied or the
    stage declares no ``weights`` — both are valid configurations (e.g. no eval
    has published a snapshot for this policy yet). Otherwise, every
    candidate's :attr:`~backend.agents.registry_v2.AgentRef.score` is
    overwritten with a blended value so the final deterministic sort (forced
    to :data:`SCORE_WEIGHTED_OBJECTIVE` by the caller) ranks by it:

    ``blended = weights.quality * quality + weights.cost * (1 - norm(cost)) +
    weights.latency * (1 - norm(latency))``

    where ``quality`` is the snapshot's ``[0, 1]`` quality aggregate taken
    as-is, and ``cost``/``latency`` are min-max normalized to ``[0, 1]``
    across the *current candidate pool* before being inverted (so lower
    cost/latency contributes a higher score) — this keeps all three terms on
    a comparable scale despite quality being a normalized score and
    cost/latency being raw USD/seconds, without requiring ``weights`` to sum
    to 1. A candidate absent from the snapshot gets a neutral ``0.0`` score.

    Args:
        candidates: The candidate list to (maybe) reorder.
        spec: The score-weighted stage configuration.
        scores: An optional score snapshot to blend in.

    Returns:
        ``(candidates, applied)`` — ``candidates`` with ``.score`` overwritten
        and ``applied=True`` when weighting was actually performed; otherwise
        the input list unchanged and ``applied=False``.
    """
    if scores is None or not spec.weights:
        return list(candidates), False
    # Keyed by (agent_id, version), not bare agent_id: two registered versions
    # of the same agent can both survive the pipeline this far (capability
    # matching/cost-aware do not deduplicate by agent_id alone), and each may
    # resolve to a different snapshot entry — collapsing them by agent_id
    # would make one candidate silently inherit another version's aggregate.
    aggregates = {
        (candidate.agent_id, candidate.version): _resolve_agent_score(candidate, scores) for candidate in candidates
    }
    present = [aggregate for aggregate in aggregates.values() if aggregate is not None]
    cost_lo, cost_hi = _value_range(aggregate.cost_usd for aggregate in present)
    latency_lo, latency_hi = _value_range(aggregate.latency_seconds for aggregate in present)
    weighted: list[AgentRef] = []
    for candidate in candidates:
        aggregate = aggregates[(candidate.agent_id, candidate.version)]
        if aggregate is None:
            weighted.append(replace(candidate, score=0.0))
            continue
        cost_score = 1.0 - _normalize(aggregate.cost_usd, cost_lo, cost_hi)
        latency_score = 1.0 - _normalize(aggregate.latency_seconds, latency_lo, latency_hi)
        blended = (
            spec.weights.get("quality", 0.0) * aggregate.quality
            + spec.weights.get("cost", 0.0) * cost_score
            + spec.weights.get("latency", 0.0) * latency_score
        )
        weighted.append(replace(candidate, score=blended))
    return weighted, True


def _resolve_agent_score(candidate: AgentRef, scores: ScoreSnapshot) -> AgentScoreAggregate | None:
    """Look up a candidate's aggregate in a score snapshot, if present.

    Checks both ``agent_id@version`` and bare ``agent_id`` keys (per
    :class:`~backend.routing.contract.ScoreSnapshot`'s documented mapping
    convention), preferring the more specific versioned key first — a
    snapshot carrying both a version-specific entry and a bare-agent_id entry
    for the same agent should resolve to the version-specific one, not have it
    shadowed by the less specific key. Prefers ``scores.agent_scores`` (the
    detailed breakdown) over the flat ``scores.scores`` mapping (a bare
    quality scalar, for snapshots published before per-dimension aggregates
    existed or constructed by a caller that only has a single blended number).

    Args:
        candidate: The candidate agent reference to look up.
        scores: The score snapshot to search.

    Returns:
        The candidate's aggregate, or ``None`` if it has no entry.
    """
    versioned_key = f"{candidate.agent_id}@{candidate.version}"
    for key in (versioned_key, candidate.agent_id):
        if key in scores.agent_scores:
            return scores.agent_scores[key]
    for key in (versioned_key, candidate.agent_id):
        if key in scores.scores:
            return AgentScoreAggregate(quality=scores.scores[key])
    return None


def _value_range(values: Iterable[float]) -> tuple[float, float]:
    """Compute the ``(min, max)`` of a value iterable, defaulting to ``(0.0, 0.0)``.

    Args:
        values: The values to range over.

    Returns:
        ``(min, max)``, or ``(0.0, 0.0)`` if ``values`` is empty.
    """
    materialized = list(values)
    if not materialized:
        return 0.0, 0.0
    return min(materialized), max(materialized)


def _normalize(value: float, lo: float, hi: float) -> float:
    """Min-max normalize ``value`` into ``[0, 1]`` given a pool's ``(lo, hi)`` range.

    Args:
        value: The value to normalize.
        lo: The pool's minimum value.
        hi: The pool's maximum value.

    Returns:
        ``(value - lo) / (hi - lo)``, or ``0.5`` when ``hi <= lo`` — either
        every present candidate shares the same value (normalization is
        undefined; a constant midpoint offset does not change their relative
        ranking against each other) or there is exactly one present candidate
        (whose actual cost/latency magnitude has nothing to compare against).
        A neutral ``0.5`` avoids inverting to a false "best possible" ``1.0``
        for a candidate that happens to be alone in having snapshot data,
        regardless of how large its actual cost/latency is.
    """
    if hi <= lo:
        return 0.5
    return (value - lo) / (hi - lo)


__all__ = ["SCORE_WEIGHTED_OBJECTIVE", "apply_score_weighted"]
