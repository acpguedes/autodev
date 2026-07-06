"""Eval -> routing feedback loop: promotion/regression guard (E5-S4).

Closes the loop reference §9.5 describes: a :class:`~backend.routing.contract.ScoreSnapshot`
published by :meth:`backend.evals.service.EvaluationService.publish_snapshot`
is not automatically applied to a routing policy's ``score-weighted``
selector stage — it must first be *promoted* against the policy's current
baseline snapshot. :class:`RoutingFeedbackService` makes that promotion
decision, guarded against noisy/small-sample flips (hysteresis) and against
genuine regressions, and records every decision — promoted or blocked — as an
auditable event, never a silent policy mutation (reference §9.5's closing
sentence).

The promotion criterion reuses reference §9.4's ``online.ab_test`` shape
(:class:`~backend.evals.contract.ABTestSpec`): ``min_samples`` is the
hysteresis guard (too few contributing eval runs never promotes, regardless
of how good a candidate snapshot looks), and ``promote_if`` is a boolean
expression comparing the candidate ("variant") snapshot's overall aggregate
against the current baseline ("control") snapshot's overall aggregate, e.g.
``"variant.quality >= control.quality and variant.cost <= control.cost"``.

This expression is evaluated with :func:`backend.evals.expressions.evaluate_expression`
rather than the ``key -> literal`` predicate matchers used by
:mod:`backend.reasoning.selection` or :mod:`backend.routing.router`: those
match one flattened signal against a literal/operator-expression string, but
``promote_if`` compares two *paths* (``variant.quality`` against
``control.quality``) joined by ``and``/``or`` — exactly the dotted-identifier
boolean-expression grammar :mod:`backend.evals.expressions` already
implements for ``gate.fail_if`` (same package as :class:`ABTestSpec`, same
grammar). Reusing it avoids building a fourth predicate parser for a shape
the other two matchers do not natively support.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from backend.evals.contract import ABTestSpec
from backend.evals.expressions import ExpressionError, evaluate_expression
from backend.routing.contract import AgentScoreAggregate, ScoreSnapshot, TraceEvent


class ScoreSnapshotStore(Protocol):
    """Structural interface for the durable score-snapshot/promotion store.

    Concrete implementations live on :class:`~backend.persistence.sqlite_adapter.SQLiteStore`
    and ``PostgresStore``, selected via :func:`backend.persistence.database.get_store`
    (the same store :class:`backend.evals.service.EvaluationService` publishes
    snapshots to).
    """

    def get_score_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Fetch one persisted score snapshot document, or ``None``."""
        ...

    def record_snapshot_promotion(
        self,
        *,
        policy_id: str,
        snapshot_id: str,
        baseline_snapshot_id: str,
        promoted: bool,
        reason: str,
        decided_at: str,
    ) -> None:
        """Append one promotion decision (promoted or blocked) to the audit log."""
        ...

    def get_active_score_snapshot(self, policy_id: str) -> dict[str, Any] | None:
        """Fetch the currently promoted snapshot document for a policy id, or ``None``."""
        ...

    def list_snapshot_promotions(self, policy_id: str) -> list[dict[str, Any]]:
        """List every promotion decision recorded for a policy id, newest first."""
        ...


@dataclass(frozen=True)
class PromotionDecision:
    """The outcome of evaluating a candidate snapshot for promotion (E5-S4).

    Attributes:
        policy_id: Routing policy id this decision applies to.
        snapshot_id: Id of the candidate ("variant") snapshot evaluated.
        baseline_snapshot_id: Id of the baseline ("control") snapshot compared
            against, or ``""`` if there was no prior active snapshot.
        promoted: Whether the candidate became the policy's active snapshot.
        reason: Human-readable explanation, separate from machine-readable
            fields (repository working-style convention).
        decided_at: ISO-8601 UTC timestamp the decision was made.
    """

    policy_id: str
    snapshot_id: str
    baseline_snapshot_id: str
    promoted: bool
    reason: str
    decided_at: str

    def to_document(self) -> dict[str, Any]:
        """Render this decision as a JSON-serializable document."""
        return {
            "policyId": self.policy_id,
            "snapshotId": self.snapshot_id,
            "baselineSnapshotId": self.baseline_snapshot_id,
            "promoted": self.promoted,
            "reason": self.reason,
            "decidedAt": self.decided_at,
        }


class RoutingFeedbackService:
    """Decides whether a published score snapshot is promoted for a routing policy.

    Stateless aside from the durable store: every call re-reads whatever
    baseline is currently active for ``policy_id``, so decisions are always
    made against the latest committed state (no in-memory drift across
    instances/requests).
    """

    def __init__(self, store: ScoreSnapshotStore, *, on_event: Callable[[TraceEvent], None] | None = None) -> None:
        """Initialize the service with a durable store and an optional trace sink.

        Args:
            store: Durable store holding published snapshots and the
                promotion audit log.
            on_event: Trace sink; receives ``selector.policy.*`` lifecycle events.
        """
        self._store = store
        self._on_event = on_event

    def get_active_snapshot(self, policy_id: str) -> ScoreSnapshot | None:
        """Fetch the snapshot currently promoted for a routing policy, if any.

        Args:
            policy_id: Routing policy id (:attr:`~backend.routing.policy.RoutingPolicy.id`).

        Returns:
            The active :class:`~backend.routing.contract.ScoreSnapshot`, or
            ``None`` if no snapshot has ever been promoted for this policy.
        """
        document = self._store.get_active_score_snapshot(policy_id)
        return ScoreSnapshot.from_document(document) if document is not None else None

    def list_promotions(self, policy_id: str) -> list[PromotionDecision]:
        """List every promotion decision recorded for a policy id, newest first.

        Args:
            policy_id: Routing policy id.

        Returns:
            The recorded decisions, most recent first.
        """
        return [
            PromotionDecision(
                policy_id=document["policyId"],
                snapshot_id=document["snapshotId"],
                baseline_snapshot_id=document["baselineSnapshotId"],
                promoted=bool(document["promoted"]),
                reason=document["reason"],
                decided_at=document["decidedAt"],
            )
            for document in self._store.list_snapshot_promotions(policy_id)
        ]

    def decide_promotion(
        self,
        candidate: ScoreSnapshot,
        *,
        policy_id: str,
        ab_test: ABTestSpec,
        baseline: ScoreSnapshot | None = None,
    ) -> PromotionDecision:
        """Decide whether ``candidate`` becomes ``policy_id``'s active snapshot.

        Two guards, both fail-closed (reference §9.6): (1) a hysteresis guard
        — ``candidate.sample_count`` must meet ``ab_test.min_samples`` (``0``
        means no minimum, mirroring ``SelectBudget``'s "0 = unconstrained"
        convention), else the candidate is blocked regardless of how it
        compares to the baseline; (2) a regression guard — ``ab_test.promote_if``
        (empty string means "always promote once the sample guard passes") is
        evaluated against ``{"variant": candidate's overall aggregate,
        "control": baseline's overall aggregate}``; a baseline-less policy
        (first-ever snapshot) compares against an all-zero control aggregate.
        The decision is persisted either way — a blocked candidate is not
        silently dropped, it is recorded as *not* promoted, so the regression
        itself is auditable.

        Args:
            candidate: The newly published ("variant") snapshot to evaluate.
            policy_id: Routing policy id this decision applies to.
            ab_test: The promotion criterion (``promote_if``, ``min_samples``).
            baseline: The ("control") snapshot to compare against; if omitted,
                the policy's current active snapshot (if any) is used.

        Returns:
            The :class:`PromotionDecision`, already persisted and traced.
        """
        if baseline is None:
            baseline = self.get_active_snapshot(policy_id)
        baseline_id = baseline.snapshot_id if baseline is not None else ""

        if ab_test.min_samples > 0 and candidate.sample_count < ab_test.min_samples:
            reason = f"insufficient samples: {candidate.sample_count} < min_samples={ab_test.min_samples}"
            return self._block(policy_id, candidate.snapshot_id, baseline_id, reason=reason)

        if ab_test.promote_if:
            control_aggregate = _overall_aggregate(baseline) if baseline is not None else AgentScoreAggregate()
            context = {
                "variant": _promote_if_fields(_overall_aggregate(candidate)),
                "control": _promote_if_fields(control_aggregate),
            }
            try:
                should_promote = evaluate_expression(ab_test.promote_if, context)
            except ExpressionError as exc:
                return self._block(
                    policy_id,
                    candidate.snapshot_id,
                    baseline_id,
                    reason=f"invalid promote_if expression {ab_test.promote_if!r}: {exc}",
                )
            if not should_promote:
                return self._block(
                    policy_id,
                    candidate.snapshot_id,
                    baseline_id,
                    reason=f"promote_if did not hold: {ab_test.promote_if}",
                )

        return self._promote(policy_id, candidate.snapshot_id, baseline_id)

    def _promote(self, policy_id: str, snapshot_id: str, baseline_snapshot_id: str) -> PromotionDecision:
        """Record and trace a successful promotion.

        Args:
            policy_id: Routing policy id.
            snapshot_id: Id of the promoted snapshot.
            baseline_snapshot_id: Id of the previous baseline, or ``""``.

        Returns:
            The persisted :class:`PromotionDecision`.
        """
        reason = "promotion criterion satisfied"
        decided_at = _utcnow()
        self._store.record_snapshot_promotion(
            policy_id=policy_id,
            snapshot_id=snapshot_id,
            baseline_snapshot_id=baseline_snapshot_id,
            promoted=True,
            reason=reason,
            decided_at=decided_at,
        )
        decision = PromotionDecision(
            policy_id=policy_id,
            snapshot_id=snapshot_id,
            baseline_snapshot_id=baseline_snapshot_id,
            promoted=True,
            reason=reason,
            decided_at=decided_at,
        )
        self._emit("selector.policy.adjusted", decision)
        return decision

    def _block(self, policy_id: str, snapshot_id: str, baseline_snapshot_id: str, *, reason: str) -> PromotionDecision:
        """Record and trace a blocked promotion (guard or regression).

        Args:
            policy_id: Routing policy id.
            snapshot_id: Id of the candidate snapshot that was blocked.
            baseline_snapshot_id: Id of the current baseline, or ``""``.
            reason: Human-readable explanation of why promotion was blocked.

        Returns:
            The persisted :class:`PromotionDecision`.
        """
        decided_at = _utcnow()
        self._store.record_snapshot_promotion(
            policy_id=policy_id,
            snapshot_id=snapshot_id,
            baseline_snapshot_id=baseline_snapshot_id,
            promoted=False,
            reason=reason,
            decided_at=decided_at,
        )
        decision = PromotionDecision(
            policy_id=policy_id,
            snapshot_id=snapshot_id,
            baseline_snapshot_id=baseline_snapshot_id,
            promoted=False,
            reason=reason,
            decided_at=decided_at,
        )
        self._emit("selector.policy.regression_blocked", decision)
        return decision

    def _emit(self, name: str, decision: PromotionDecision) -> None:
        """Emit a policy-change lifecycle event to the trace sink, if configured.

        Args:
            name: Dotted event name.
            decision: The decision to record as the event's payload.
        """
        if self._on_event is not None:
            self._on_event(TraceEvent(sequence=-1, name=name, payload=decision.to_document(), timestamp=time.time()))


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _overall_aggregate(snapshot: ScoreSnapshot) -> AgentScoreAggregate:
    """Collapse a snapshot's per-agent aggregates into one policy-level aggregate.

    Weighted by each agent's ``sample_count`` (agents with more contributing
    runs influence the overall figure proportionally more); an agent with
    ``sample_count == 0`` is treated as contributing a single nominal sample so
    it is not silently dropped from the average.

    Args:
        snapshot: The snapshot to collapse.

    Returns:
        The overall :class:`~backend.routing.contract.AgentScoreAggregate`
        across every agent in ``snapshot``; all-zero if it has none.
    """
    aggregates = list(snapshot.agent_scores.values())
    if not aggregates:
        return AgentScoreAggregate()
    weights = [max(aggregate.sample_count, 1) for aggregate in aggregates]
    total_weight = sum(weights)
    return AgentScoreAggregate(
        quality=sum(a.quality * w for a, w in zip(aggregates, weights)) / total_weight,
        cost_usd=sum(a.cost_usd * w for a, w in zip(aggregates, weights)) / total_weight,
        latency_seconds=sum(a.latency_seconds * w for a, w in zip(aggregates, weights)) / total_weight,
        sample_count=sum(aggregate.sample_count for aggregate in aggregates),
    )


def _promote_if_fields(aggregate: AgentScoreAggregate) -> dict[str, float]:
    """Render an aggregate using the ``promote_if`` DSL's field names.

    Deliberately **not** :meth:`AgentScoreAggregate.to_document` — that method
    uses the persisted-document key names (``costUsd``, ``latencySeconds``,
    ``sampleCount``), but reference §9.4's ``promote_if`` grammar (and every
    example of it, including this module's own docstring) addresses fields as
    ``variant.quality``/``variant.cost``/``variant.latency``. Using the
    persisted key names directly in the expression context would make any
    ``promote_if`` written against the documented DSL raise
    :class:`~backend.evals.expressions.ExpressionError` (unknown field
    ``cost``/``latency``) and fail closed every time, silently blocking every
    promotion that follows the reference documentation's own example.

    Args:
        aggregate: The aggregate to render.

    Returns:
        ``{"quality": ..., "cost": ..., "latency": ...}`` — sample count is
        deliberately omitted; it is not part of the ``promote_if`` grammar
        (guarded separately by ``min_samples``).
    """
    return {"quality": aggregate.quality, "cost": aggregate.cost_usd, "latency": aggregate.latency_seconds}


__all__ = ["PromotionDecision", "RoutingFeedbackService", "ScoreSnapshotStore"]
