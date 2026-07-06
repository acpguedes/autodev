"""Closed-loop and end-to-end tests for the E5-S4 eval -> routing feedback loop.

Covers the story DoD: a promoted snapshot changing a subsequent Selector
decision (the closed feedback loop, reference §9.5), a regression-blocked
snapshot leaving that decision unaffected, the closed loop not introducing
non-determinism into the Selector's tie-breaking, and the full flow exercised
through the real FastAPI app (``POST /v2/evals/{namespace}/{name}/publish``
followed by ``POST /v2/select``).

Signal-publishing and promotion/regression-guard unit tests (without a
Selector/registry in the loop) live in :mod:`test_routing_feedback` — split
out to keep both files under the repository's file-size guideline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.agents.manifest import validate_agent_manifest
from backend.agents.registry_v2 import AgentRegistry
from backend.evals.contract import ABTestSpec
from backend.evals.results import EvalResult, EvaluatorResult, RunMetrics
from backend.evals.service import EvaluationService
from backend.persistence.database import DurableStore
from backend.routing.contract import (
    RouteConstraints,
    RouteDecision,
    SelectBudget,
    SelectRequest,
    TraceEvent,
)
from backend.routing.feedback import RoutingFeedbackService
from backend.routing.policy import (
    RoutingPolicy,
    SelectorCapabilityMatchingStageSpec,
    SelectorCostAwareStageSpec,
    SelectorPipelineSpec,
    SelectorPolicySpec,
    SelectorScoreWeightedStageSpec,
    default_routing_policy,
)
from backend.routing.selector import Selector

POLICY_ID = "acme/routing-feedback-test"


# ---------------------------------------------------------------------------
# Shared fixtures/helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> DurableStore:
    """A SQLiteStore backed by a throwaway database file, exercising the real tables."""
    return DurableStore(f"sqlite:///{tmp_path / 'feedback_e2e_test.db'}")


def _agent_manifest(agent_id: str, *, cost_usd: float = 0.5) -> dict[str, Any]:
    """Build a raw agent manifest document for feedback-loop tests."""
    return {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": agent_id,
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": "code.implementation", "version": "1.0.0", "level": "primary"}],
        "io": {
            "contract": "acme/feedback-io",
            "contractVersion": "1.0.0",
            "input": {"type": "object", "additionalProperties": True},
            "output": {"type": "object", "additionalProperties": True},
        },
        "entrypoint": {"runtime": "python", "ref": "agent_module:Agent"},
        "budgets": {"tokens": {"input": 1000, "output": 500}, "costUsd": cost_usd, "wallClockSeconds": 60},
    }


def _register(registry: AgentRegistry, agent_id: str, *, cost_usd: float = 0.5) -> None:
    """Validate and register an agent manifest built by :func:`_agent_manifest`."""
    result = validate_agent_manifest(_agent_manifest(agent_id, cost_usd=cost_usd))
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="acme/plugin")


def _select_request() -> SelectRequest:
    """Build a minimal SelectRequest for a routed 'add-feature' task."""
    route = RouteDecision(
        schema_version="1.0",
        task_type="existing-repo-change",
        intent="add-feature",
        path=("navigator", "coder", "responder"),
        confidence=1.0,
        constraints=RouteConstraints(max_cost_usd=0.05, latency_class="interactive"),
        rationale="test fixture",
    )
    return SelectRequest(
        schema_version="1.0",
        route=route,
        required_capabilities=("code.implementation",),
        budget=SelectBudget(tokens=0, cost_usd=0.0, time_s=0),
    )


def _score_weighted_policy() -> RoutingPolicy:
    """A RoutingPolicy with capability-matching -> cost-aware -> score-weighted -> lowest_cost."""
    base = default_routing_policy()
    return RoutingPolicy(
        schema_version=base.schema_version,
        id=POLICY_ID,
        version=base.version,
        host_api=base.host_api,
        router=base.router,
        selector=SelectorPolicySpec(
            pipeline=SelectorPipelineSpec(
                stages=(
                    SelectorCapabilityMatchingStageSpec(require_all=True),
                    SelectorCostAwareStageSpec(objective="minimize_cost"),
                    SelectorScoreWeightedStageSpec(weights={"quality": 0.6, "cost": 0.25, "latency": 0.15}),
                ),
                tie_breaker="lowest_cost",
            )
        ),
    )


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
# Closed feedback loop: a promoted snapshot changes a subsequent selection
# ---------------------------------------------------------------------------


def test_closed_loop_promoted_snapshot_changes_the_selector_decision(store: DurableStore) -> None:
    """A published + promoted snapshot changes a subsequent Selector decision.

    Two agents: the cheap one wins on cost alone; the expensive one has a
    much higher published quality. Once the resulting snapshot is promoted,
    the score-weighted stage's quality weighting outranks pure cost-minimizing
    for the same SelectRequest.
    """
    registry = AgentRegistry(store)
    _register(registry, "acme/cheap", cost_usd=0.1)
    _register(registry, "acme/expensive", cost_usd=0.9)
    policy = _score_weighted_policy()
    req = _select_request()

    before = Selector().select(req, policy, registry)
    assert before.agent_id == "acme/cheap"
    assert before.score_basis == ""

    eval_service = EvaluationService(store)
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/expensive",
        quality=1.0, cost_usd=0.9, latency_seconds=1.0,
    )
    snapshot = eval_service.publish_snapshot("acme/eval-bugfix")
    feedback = RoutingFeedbackService(store)
    decision = feedback.decide_promotion(snapshot, policy_id=policy.id, ab_test=ABTestSpec(min_samples=1))
    assert decision.promoted is True

    active_snapshot = feedback.get_active_snapshot(policy.id)
    after = Selector().select(req, policy, registry, active_snapshot)

    assert after.agent_id == "acme/expensive"
    assert after.score_basis == snapshot.snapshot_id
    assert after != before


def test_closed_loop_regression_blocked_selection_stays_unaffected(store: DurableStore) -> None:
    """A blocked (regressed) candidate must not change the Selector's decision.

    Mirrors the prior test's setup, but the candidate snapshot regresses on
    ``promote_if`` (lower quality than the ``0.9`` floor required) — the
    Selector must keep picking the cheap agent exactly as it did before any
    snapshot existed, and the block must be traced.
    """
    registry = AgentRegistry(store)
    _register(registry, "acme/cheap", cost_usd=0.1)
    _register(registry, "acme/expensive", cost_usd=0.9)
    policy = _score_weighted_policy()
    req = _select_request()

    baseline_decision = Selector().select(req, policy, registry)
    assert baseline_decision.agent_id == "acme/cheap"

    eval_service = EvaluationService(store)
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/expensive",
        quality=0.2, cost_usd=0.9, latency_seconds=1.0,
    )
    snapshot = eval_service.publish_snapshot("acme/eval-bugfix")
    events: list[TraceEvent] = []
    feedback = RoutingFeedbackService(store, on_event=events.append)
    decision = feedback.decide_promotion(
        snapshot, policy_id=policy.id, ab_test=ABTestSpec(promote_if="variant.quality >= 0.9", min_samples=1)
    )

    assert decision.promoted is False
    assert events[0].name == "selector.policy.regression_blocked"

    active_snapshot = feedback.get_active_snapshot(policy.id)
    assert active_snapshot is None
    after = Selector().select(req, policy, registry, active_snapshot)
    assert after.agent_id == baseline_decision.agent_id == "acme/cheap"


def test_selection_is_deterministic_across_repeated_calls_with_the_same_snapshot(store: DurableStore) -> None:
    """Repeated selections against the same promoted snapshot yield the exact same decision.

    Guards against the closed loop introducing non-determinism into the
    Selector's final tie-break (e.g. via dict/set iteration order feeding the
    score-weighted normalization).
    """
    registry = AgentRegistry(store)
    _register(registry, "acme/agent-a", cost_usd=0.3)
    _register(registry, "acme/agent-b", cost_usd=0.3)
    _register(registry, "acme/agent-c", cost_usd=0.3)
    policy = _score_weighted_policy()
    req = _select_request()

    eval_service = EvaluationService(store)
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/agent-a",
        quality=0.7, cost_usd=0.3, latency_seconds=5.0,
    )
    _persist_result(
        store, eval_id="acme/eval-bugfix", run_id="r2", agent_id="acme/agent-b",
        quality=0.7, cost_usd=0.3, latency_seconds=5.0,
    )
    snapshot = eval_service.publish_snapshot("acme/eval-bugfix")
    feedback = RoutingFeedbackService(store)
    feedback.decide_promotion(snapshot, policy_id=policy.id, ab_test=ABTestSpec(min_samples=1))
    active_snapshot = feedback.get_active_snapshot(policy.id)

    decisions = [Selector().select(req, policy, registry, active_snapshot) for _ in range(5)]

    assert len(set(decisions)) == 1


# ---------------------------------------------------------------------------
# End-to-end via the real ASGI app (/v2/evals/.../publish + /v2/select)
# ---------------------------------------------------------------------------


def test_publish_endpoint_promotes_and_changes_subsequent_select_via_http(store: DurableStore) -> None:
    """POST /v2/evals/{ns}/{name}/publish promotes a snapshot that then changes POST /v2/select.

    Exercises the full closed loop through the real FastAPI app (in-process
    ASGI, no separate server process needed), wiring the agent registry and
    the durable store shared by the Evaluation/Feedback services to one
    ``tmp_path``-backed instance via ``app.dependency_overrides`` — mirroring
    ``test_agents_v2_registry.py``'s ``get_agent_registry`` override pattern.
    ``/v2/select`` itself is exercised unmodified (``get_routing_service``'s
    real default, ``default_routing_policy()``, already declares a
    ``score-weighted`` stage per reference §9.3's example — see E5-S4's
    amendment to ``default_routing_policy()``).
    """
    from backend.api.main import app
    from backend.api.routers.agents_v2 import get_agent_registry
    from backend.api.routers.evals import get_evaluation_service, get_routing_feedback_service as get_evals_feedback
    from backend.api.routers.routing import get_routing_feedback_service

    registry = AgentRegistry(store)
    _register(registry, "acme/cheap", cost_usd=0.1)
    _register(registry, "acme/expensive", cost_usd=0.9)
    policy_id = default_routing_policy().id

    app.dependency_overrides[get_agent_registry] = lambda: registry
    app.dependency_overrides[get_routing_feedback_service] = lambda: RoutingFeedbackService(store)
    app.dependency_overrides[get_evals_feedback] = lambda: RoutingFeedbackService(store)
    app.dependency_overrides[get_evaluation_service] = lambda: EvaluationService(store)
    try:
        client = TestClient(app)
        select_body = {
            "route": {"task_type": "existing-repo-change", "intent": "add-feature", "path": ["coder"]},
            "required_capabilities": ["code.implementation"],
        }

        before = client.post("/v2/select", json=select_body)
        assert before.status_code == 200
        assert before.json()["agent_id"] == "acme/cheap"

        _persist_result(
            store, eval_id="acme/eval-bugfix", run_id="r1", agent_id="acme/expensive",
            quality=1.0, cost_usd=0.9, latency_seconds=1.0,
        )
        publish_response = client.post(
            "/v2/evals/acme/eval-bugfix/publish",
            json={"policyId": policy_id, "minSamples": 1},
        )
        assert publish_response.status_code == 201
        publish_body = publish_response.json()
        assert publish_body["promotion"]["promoted"] is True

        after = client.post("/v2/select", json=select_body)
        assert after.status_code == 200
        assert after.json()["agent_id"] == "acme/expensive"
        assert after.json()["score_basis"] == publish_body["snapshot"]["snapshotId"]
    finally:
        app.dependency_overrides.clear()


def test_publish_endpoint_rejects_missing_policy_id(store: DurableStore) -> None:
    """POST /v2/evals/{ns}/{name}/publish returns 422 when 'policyId' is missing."""
    from backend.api.main import app
    from backend.api.routers.evals import get_evaluation_service

    app.dependency_overrides[get_evaluation_service] = lambda: EvaluationService(store)
    try:
        client = TestClient(app)
        response = client.post("/v2/evals/acme/eval-bugfix/publish", json={})
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("bad_min_samples", [-1, "not-a-number", 1.5, True])
def test_publish_endpoint_rejects_malformed_min_samples(store: DurableStore, bad_min_samples: object) -> None:
    """POST /v2/evals/{ns}/{name}/publish returns 422 (not an unhandled 500) for a bad 'minSamples'.

    Regression test: `int(body.get("minSamples", 0))` on a non-numeric string
    would previously raise an uncaught ValueError, and a negative value would
    silently bypass the hysteresis guard entirely (`min_samples > 0` is false
    for negative numbers too) rather than being rejected as invalid input.
    """
    from backend.api.main import app
    from backend.api.routers.evals import get_evaluation_service

    app.dependency_overrides[get_evaluation_service] = lambda: EvaluationService(store)
    try:
        client = TestClient(app)
        response = client.post(
            "/v2/evals/acme/eval-bugfix/publish",
            json={"policyId": POLICY_ID, "minSamples": bad_min_samples},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("bad_eval_version", [123, 1.5, True, ["1.0.0"]])
def test_publish_endpoint_rejects_non_string_eval_version(store: DurableStore, bad_eval_version: object) -> None:
    """POST /v2/evals/{ns}/{name}/publish returns 422 (not an unhandled 500) for a non-string 'evalVersion'.

    Regression test: an unvalidated ``evalVersion`` flows into
    ``list_eval_results(eval_id, eval_version)``; on Postgres, comparing a
    ``TEXT`` column against a non-string parameter raises an uncaught
    ``UndefinedFunction`` (no implicit ``text = integer`` cast), escaping as a
    500 instead of a clean 422.
    """
    from backend.api.main import app
    from backend.api.routers.evals import get_evaluation_service

    app.dependency_overrides[get_evaluation_service] = lambda: EvaluationService(store)
    try:
        client = TestClient(app)
        response = client.post(
            "/v2/evals/acme/eval-bugfix/publish",
            json={"policyId": POLICY_ID, "evalVersion": bad_eval_version},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_select_endpoint_degrades_to_no_snapshot_when_the_lookup_fails(store: DurableStore) -> None:
    """POST /v2/select stays healthy (200, scores=None) even if the snapshot lookup itself fails.

    Regression test: `scores = feedback.get_active_snapshot(...)` used to sit
    outside any error handling — a snapshot-store read failure or a corrupted
    persisted document would turn an otherwise-healthy /v2/select call into an
    unrelated 500, even though `scores=None` is already a fully valid, no-op
    state for the Selector.
    """
    from backend.api.main import app
    from backend.api.routers.agents_v2 import get_agent_registry
    from backend.api.routers.routing import get_routing_feedback_service

    class _BrokenFeedback:
        """A RoutingFeedbackService stand-in whose snapshot lookup always raises."""

        def get_active_snapshot(self, policy_id: str) -> None:
            """Simulate a snapshot-store read failure."""
            raise RuntimeError("simulated snapshot store failure")

    registry = AgentRegistry(store)
    _register(registry, "acme/only-agent", cost_usd=0.5)

    app.dependency_overrides[get_agent_registry] = lambda: registry
    app.dependency_overrides[get_routing_feedback_service] = lambda: _BrokenFeedback()
    try:
        client = TestClient(app)
        response = client.post(
            "/v2/select",
            json={
                "route": {"task_type": "existing-repo-change", "intent": "add-feature", "path": ["coder"]},
                "required_capabilities": ["code.implementation"],
            },
        )
        assert response.status_code == 200
        assert response.json()["agent_id"] == "acme/only-agent"
        assert response.json()["score_basis"] == ""
    finally:
        app.dependency_overrides.clear()
