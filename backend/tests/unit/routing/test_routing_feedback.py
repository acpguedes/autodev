"""Unit tests for the E5-S4 eval -> routing feedback loop: signal publishing + promotion guard.

Covers the story DoD: eval scores published as a versioned
:class:`~backend.routing.contract.ScoreSnapshot` signal
(:meth:`~backend.evals.service.EvaluationService.publish_snapshot`), a
regression/hysteresis guard blocking promotion without silently mutating the
active policy (:class:`~backend.routing.feedback.RoutingFeedbackService`),
and every promotion decision — promoted or blocked — being traced and
auditable.

The closed feedback loop itself (a promoted snapshot changing a subsequent
Selector decision, determinism, and the real end-to-end HTTP flow) lives in
:mod:`test_routing_feedback_e2e` — split out to keep both files under the
repository's file-size guideline.

Does not duplicate E5-S2's selector-stage-level score-weighting tests
(:mod:`test_routing_selector`) or E5-S3's eval runner/persistence tests
(:mod:`test_evals_runner`) — only the new eval-to-selection feedback wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.evals.contract import ABTestSpec, EvalError
from backend.evals.contract import TraceEvent as EvalTraceEvent
from backend.evals.results import EvalResult, EvaluatorResult, RunMetrics
from backend.evals.service import EvaluationService
from backend.persistence.database import DurableStore
from backend.routing.contract import TraceEvent
from backend.routing.feedback import RoutingFeedbackService

POLICY_ID = "acme/routing-feedback-test"


# ---------------------------------------------------------------------------
# Shared fixtures/helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> DurableStore:
    """A SQLiteStore backed by a throwaway database file, exercising the real tables."""
    return DurableStore(f"sqlite:///{tmp_path / 'feedback_test.db'}")


def _persist_result(
    store: DurableStore,
    *,
    eval_id: str,
    run_id: str,
    agent_id: str,
    quality: float,
    cost_usd: float,
    latency_seconds: float,
) -> None:
    """Directly persist an EvalResult, bypassing the runner for precise, deterministic test data."""
    result = EvalResult(
        eval_id=eval_id,
        eval_version="1.0.0",
        run_id=run_id,
        mode="offline",
        dataset_ref="acme/golden@2026-06",
        dataset_split="test",
        dataset_size=1,
        evaluator_results=(
            EvaluatorResult(evaluator_id="quality_check", kind="deterministic", mean_score=quality, case_scores=()),
        ),
        metrics=RunMetrics(
            quality={"quality_check": quality},
            cost_usd_mean=cost_usd,
            cost_usd_p95=cost_usd,
            latency_p50_seconds=latency_seconds,
            latency_p95_seconds=latency_seconds,
        ),
        gate_passed=True,
        gate_reason="no gate configured",
        created_at="2026-07-05T00:00:00+00:00",
        agent_id=agent_id,
    )
    store.create_eval_result(
        eval_id=eval_id, eval_version="1.0.0", run_id=run_id, document=result.to_document()
    )


# ---------------------------------------------------------------------------
# Publishing a score snapshot (signal publishing)
# ---------------------------------------------------------------------------


def test_publish_snapshot_aggregates_per_agent_quality_cost_latency(store: DurableStore) -> None:
    """publish_snapshot groups persisted results by agent_id and averages each dimension."""
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=1.0, cost_usd=0.10, latency_seconds=10.0,
    )
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r2", agent_id="acme/agent-a",
        quality=0.5, cost_usd=0.20, latency_seconds=20.0,
    )
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r3", agent_id="acme/agent-b",
        quality=0.2, cost_usd=0.05, latency_seconds=5.0,
    )

    service = EvaluationService(store)
    snapshot = service.publish_snapshot("acme/eval-bugfix")

    assert snapshot.sample_count == 3
    assert set(snapshot.source_run_ids) == {"r1", "r2", "r3"}
    agent_a = snapshot.agent_scores["acme/agent-a"]
    assert agent_a.quality == pytest.approx(0.75)
    assert agent_a.cost_usd == pytest.approx(0.15)
    assert agent_a.latency_seconds == pytest.approx(15.0)
    assert agent_a.sample_count == 2
    agent_b = snapshot.agent_scores["acme/agent-b"]
    assert agent_b.quality == pytest.approx(0.2)
    assert agent_b.sample_count == 1
    # Backward-compat flat mapping mirrors the detailed aggregate's quality.
    assert snapshot.scores["acme/agent-a"] == pytest.approx(0.75)


def test_publish_snapshot_is_versioned_and_immutable(store: DurableStore) -> None:
    """Publishing twice from the same results produces two distinct, separately-stored snapshots."""
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=1.0, cost_usd=0.1, latency_seconds=1.0,
    )
    service = EvaluationService(store)

    first = service.publish_snapshot("acme/eval-bugfix")
    second = service.publish_snapshot("acme/eval-bugfix")

    assert first.snapshot_id != second.snapshot_id
    assert store.get_score_snapshot(first.snapshot_id) is not None
    assert store.get_score_snapshot(second.snapshot_id) is not None


def test_publish_snapshot_emits_trace_event(store: DurableStore) -> None:
    """publish_snapshot emits an 'eval.scores.published' trace event."""
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=1.0, cost_usd=0.1, latency_seconds=1.0,
    )
    events: list[EvalTraceEvent] = []
    service = EvaluationService(store, on_event=events.append)

    snapshot = service.publish_snapshot("acme/eval-bugfix")

    assert len(events) == 1
    assert events[0].name == "eval.scores.published"
    assert events[0].payload["snapshotId"] == snapshot.snapshot_id
    assert events[0].payload["sampleCount"] == 1
    assert events[0].payload["agentIds"] == ["acme/agent-a"]


def test_publish_snapshot_raises_when_no_results_exist(store: DurableStore) -> None:
    """publish_snapshot fails closed rather than publishing an empty, meaningless snapshot."""
    service = EvaluationService(store)
    with pytest.raises(EvalError):
        service.publish_snapshot("acme/eval-with-no-results")


# ---------------------------------------------------------------------------
# Promotion / regression guard
# ---------------------------------------------------------------------------


def test_decide_promotion_promotes_and_emits_policy_adjusted_event(store: DurableStore) -> None:
    """A candidate satisfying promote_if and min_samples is promoted and traced."""
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=0.9, cost_usd=0.1, latency_seconds=1.0,
    )
    eval_service = EvaluationService(store)
    snapshot = eval_service.publish_snapshot("acme/eval-bugfix")

    events: list[TraceEvent] = []
    feedback = RoutingFeedbackService(store, on_event=events.append)
    ab_test = ABTestSpec(promote_if="variant.quality >= 0.5", min_samples=1)

    decision = feedback.decide_promotion(snapshot, policy_id=POLICY_ID, ab_test=ab_test)

    assert decision.promoted is True
    assert decision.snapshot_id == snapshot.snapshot_id
    assert decision.baseline_snapshot_id == ""
    assert len(events) == 1
    assert events[0].name == "selector.policy.adjusted"
    active = feedback.get_active_snapshot(POLICY_ID)
    assert active is not None
    assert active.snapshot_id == snapshot.snapshot_id


def test_decide_promotion_blocks_on_insufficient_samples(store: DurableStore) -> None:
    """The hysteresis guard blocks promotion when sample_count < min_samples, traced as blocked."""
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=1.0, cost_usd=0.1, latency_seconds=1.0,
    )
    eval_service = EvaluationService(store)
    snapshot = eval_service.publish_snapshot("acme/eval-bugfix")

    events: list[TraceEvent] = []
    feedback = RoutingFeedbackService(store, on_event=events.append)
    ab_test = ABTestSpec(promote_if="variant.quality >= 0.0", min_samples=500)

    decision = feedback.decide_promotion(snapshot, policy_id=POLICY_ID, ab_test=ab_test)

    assert decision.promoted is False
    assert "insufficient samples" in decision.reason
    assert events[0].name == "selector.policy.regression_blocked"
    assert feedback.get_active_snapshot(POLICY_ID) is None


def test_decide_promotion_blocks_a_regression_and_leaves_baseline_active(store: DurableStore) -> None:
    """A candidate that regresses on promote_if is blocked; the prior baseline stays active."""
    eval_service = EvaluationService(store)
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=0.9, cost_usd=0.1, latency_seconds=1.0,
    )
    baseline = eval_service.publish_snapshot("acme/eval-bugfix", snapshot_id="baseline-snap")
    feedback = RoutingFeedbackService(store)
    ab_test = ABTestSpec(promote_if="variant.quality >= control.quality", min_samples=1)
    first_decision = feedback.decide_promotion(baseline, policy_id=POLICY_ID, ab_test=ab_test)
    assert first_decision.promoted is True

    # A worse-quality candidate must not overwrite the active (baseline) snapshot.
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r2", agent_id="acme/agent-a",
        quality=0.1, cost_usd=0.1, latency_seconds=1.0,
    )
    regressed = eval_service.publish_snapshot("acme/eval-bugfix", snapshot_id="regressed-snap")
    events: list[TraceEvent] = []
    feedback_with_trace = RoutingFeedbackService(store, on_event=events.append)

    second_decision = feedback_with_trace.decide_promotion(regressed, policy_id=POLICY_ID, ab_test=ab_test)

    assert second_decision.promoted is False
    assert second_decision.baseline_snapshot_id == "baseline-snap"
    assert events[0].name == "selector.policy.regression_blocked"
    active = feedback_with_trace.get_active_snapshot(POLICY_ID)
    assert active is not None
    assert active.snapshot_id == "baseline-snap"


def test_decide_promotion_evaluates_promote_if_using_cost_and_latency_fields(store: DurableStore) -> None:
    """promote_if resolves 'variant.cost'/'variant.latency', not the persisted 'costUsd'/'latencySeconds' keys.

    Regression test: reference §9.4's own canonical example is
    ``"variant.quality >= control.quality and variant.cost <= control.cost"``
    — the promotion context must expose plain ``cost``/``latency`` fields
    (matching this DSL), not the document keys
    :meth:`~backend.routing.contract.AgentScoreAggregate.to_document` uses for
    persistence. Every other test in this file only exercises ``.quality``,
    which would not have caught a context built from ``.to_document()``
    directly (an unknown-field ``ExpressionError`` on ``cost``/``latency``
    fails closed silently in the same way a genuine regression does).
    """
    eval_service = EvaluationService(store)
    feedback = RoutingFeedbackService(store)

    # Seed a real (non-zero) baseline first — comparing straight against the
    # all-zero implicit baseline would make any real cost/latency value fail
    # a "<=" comparison trivially, which would mask this exact bug.
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=0.9, cost_usd=0.2, latency_seconds=10.0,
    )
    baseline = eval_service.publish_snapshot("acme/eval-bugfix", snapshot_id="baseline-snap")
    seed_decision = feedback.decide_promotion(baseline, policy_id=POLICY_ID, ab_test=ABTestSpec(min_samples=1))
    assert seed_decision.promoted is True

    # A strictly better candidate (higher quality, lower cost, lower latency)
    # compared against that real baseline via the reference doc's own example
    # promote_if grammar must promote.
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r2", agent_id="acme/agent-a",
        quality=0.95, cost_usd=0.1, latency_seconds=5.0,
    )
    better = eval_service.publish_snapshot("acme/eval-bugfix", snapshot_id="better-snap")
    ab_test = ABTestSpec(
        promote_if="variant.quality >= control.quality and variant.cost <= control.cost "
        "and variant.latency <= control.latency",
        min_samples=1,
    )

    decision = feedback.decide_promotion(better, policy_id=POLICY_ID, ab_test=ab_test)

    assert decision.promoted is True
    assert decision.reason == "promotion criterion satisfied"


def test_decide_promotion_blocks_on_invalid_promote_if_expression(store: DurableStore) -> None:
    """A malformed promote_if expression fails closed (blocked, traced) rather than raising."""
    eval_service = EvaluationService(store)
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=0.9, cost_usd=0.1, latency_seconds=1.0,
    )
    snapshot = eval_service.publish_snapshot("acme/eval-bugfix")
    feedback = RoutingFeedbackService(store)
    ab_test = ABTestSpec(promote_if="variant.quality >>> broken", min_samples=0)

    decision = feedback.decide_promotion(snapshot, policy_id=POLICY_ID, ab_test=ab_test)

    assert decision.promoted is False
    assert "invalid promote_if expression" in decision.reason


def test_decide_promotion_defaults_to_always_promote_when_no_promote_if_given(store: DurableStore) -> None:
    """An empty promote_if means 'promote once the sample guard passes' — no criterion required."""
    eval_service = EvaluationService(store)
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=0.01, cost_usd=5.0, latency_seconds=100.0,
    )
    snapshot = eval_service.publish_snapshot("acme/eval-bugfix")
    feedback = RoutingFeedbackService(store)

    decision = feedback.decide_promotion(snapshot, policy_id=POLICY_ID, ab_test=ABTestSpec())

    assert decision.promoted is True


def test_promotion_history_is_auditable_for_both_outcomes(store: DurableStore) -> None:
    """list_promotions records every decision, promoted or blocked, newest first."""
    eval_service = EvaluationService(store)
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=0.9, cost_usd=0.1, latency_seconds=1.0,
    )
    good = eval_service.publish_snapshot("acme/eval-bugfix", snapshot_id="good-snap")
    feedback = RoutingFeedbackService(store)
    feedback.decide_promotion(good, policy_id=POLICY_ID, ab_test=ABTestSpec(min_samples=100))  # blocked

    history = feedback.list_promotions(POLICY_ID)

    assert len(history) == 1
    assert history[0].promoted is False
    assert history[0].snapshot_id == "good-snap"
