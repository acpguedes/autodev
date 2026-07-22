"""Closed feedback loop, driven by the real reference eval (E12-S3).

Extends :mod:`test_routing_feedback_e2e`'s closed-loop proof (which persists a
hand-built :class:`~backend.evals.results.EvalResult` directly) one layer
further out: this test actually *runs* the versioned reference eval shipped
at ``evals/reference/agent_smoke/eval.yaml`` — the same spec exercised by
``make eval-reference`` and ``.github/workflows/ci-evals.yml`` — through the
full offline pipeline (:func:`backend.evals.spec.load_eval_spec`,
:func:`backend.evals.dataset_loader.load_eval_cases`,
:meth:`backend.evals.service.EvaluationService.run_offline`), then proves the
result's published snapshot, once promoted, changes a subsequent
:class:`~backend.routing.selector.Selector` decision — the story's DoD for
"the closed feedback loop is exercised end-to-end by an on-demand-triggerable
eval".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.agents.manifest import validate_agent_manifest
from backend.agents.registry_v2 import AgentRegistry
from backend.evals.contract import ABTestSpec
from backend.evals.dataset_loader import load_eval_cases, resolve_dataset_path
from backend.evals.service import EvaluationService
from backend.evals.spec import load_eval_spec
from backend.persistence.database import DurableStore
from backend.routing.contract import RouteConstraints, RouteDecision, SelectBudget, SelectRequest
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

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REFERENCE_SPEC_PATH = _REPO_ROOT / "evals" / "reference" / "agent_smoke" / "eval.yaml"
POLICY_ID = "autodev/reference-eval-feedback-test"


@pytest.fixture()
def store(tmp_path: Path) -> DurableStore:
    """A SQLiteStore backed by a throwaway database file, exercising the real tables."""
    return DurableStore(f"sqlite:///{tmp_path / 'reference_eval_feedback_test.db'}")


def _agent_manifest(agent_id: str, *, cost_usd: float) -> dict[str, Any]:
    """Build a raw agent manifest document for the closed-loop fixture agents."""
    return {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": agent_id,
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": "code.implementation", "version": "1.0.0", "level": "primary"}],
        "io": {
            "contract": "autodev/reference-eval-io",
            "contractVersion": "1.0.0",
            "input": {"type": "object", "additionalProperties": True},
            "output": {"type": "object", "additionalProperties": True},
        },
        "entrypoint": {"runtime": "python", "ref": "agent_module:Agent"},
        "budgets": {"tokens": {"input": 1000, "output": 500}, "costUsd": cost_usd, "wallClockSeconds": 60},
    }


def _register(registry: AgentRegistry, agent_id: str, *, cost_usd: float) -> None:
    """Validate and register an agent manifest built by :func:`_agent_manifest`."""
    result = validate_agent_manifest(_agent_manifest(agent_id, cost_usd=cost_usd))
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="autodev/plugin")


def _select_request() -> SelectRequest:
    """Build a minimal SelectRequest matching the reference eval's target capability."""
    route = RouteDecision(
        schema_version="1.0",
        task_type="existing-repo-change",
        intent="add-feature",
        path=("navigator", "coder", "responder"),
        confidence=1.0,
        constraints=RouteConstraints(max_cost_usd=1.0, latency_class="interactive"),
        rationale="reference-eval closed-loop test fixture",
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


def test_running_the_reference_eval_promotes_a_snapshot_that_changes_selection(store: DurableStore) -> None:
    """Run evals/reference/agent_smoke/eval.yaml end-to-end and prove the closed loop.

    Before any eval has run, the cheap, unevaluated agent wins purely on cost.
    After running the reference eval for ``autodev/agent-coder`` (its declared
    ``target.agent_id``), publishing the resulting snapshot, and promoting it,
    the score-weighted stage's quality weighting flips the decision to the
    evaluated agent — even though it remains the more expensive candidate.
    """
    spec = load_eval_spec(_REFERENCE_SPEC_PATH)
    dataset_path = resolve_dataset_path(_REFERENCE_SPEC_PATH, spec.dataset.ref)
    cases = load_eval_cases(dataset_path)

    registry = AgentRegistry(store)
    _register(registry, spec.target.agent_id, cost_usd=0.9)
    _register(registry, "autodev/other-agent", cost_usd=0.1)
    policy = _score_weighted_policy()
    req = _select_request()

    before = Selector().select(req, policy, registry)
    assert before.agent_id == "autodev/other-agent"
    assert before.score_basis == ""

    eval_service = EvaluationService(store)
    result = eval_service.run_offline(spec, cases)
    assert result.gate_passed is True
    assert result.agent_id == spec.target.agent_id

    snapshot = eval_service.publish_snapshot(spec.id, eval_version=spec.version)
    assert snapshot.agent_scores[spec.target.agent_id].quality == pytest.approx(1.0)

    feedback = RoutingFeedbackService(store)
    decision = feedback.decide_promotion(snapshot, policy_id=policy.id, ab_test=ABTestSpec(min_samples=1))
    assert decision.promoted is True

    active_snapshot = feedback.get_active_snapshot(policy.id)
    after = Selector().select(req, policy, registry, active_snapshot)

    assert after.agent_id == spec.target.agent_id
    assert after.score_basis == snapshot.snapshot_id
    assert after.agent_id != before.agent_id


def test_running_the_reference_eval_twice_produces_immutable_distinct_results(store: DurableStore) -> None:
    """Re-running the reference eval never overwrites a prior result (ADR-009).

    Guards the eval-run side of the closed loop this story adds: two
    consecutive ``run_offline`` calls for the same spec produce two distinct,
    independently retrievable ``run_id``s, and ``publish_snapshot`` aggregates
    across both.
    """
    spec = load_eval_spec(_REFERENCE_SPEC_PATH)
    dataset_path = resolve_dataset_path(_REFERENCE_SPEC_PATH, spec.dataset.ref)
    cases = load_eval_cases(dataset_path)
    eval_service = EvaluationService(store)

    first = eval_service.run_offline(spec, cases, run_id="reference-run-1")
    second = eval_service.run_offline(spec, cases, run_id="reference-run-2")

    assert first.run_id != second.run_id
    assert eval_service.get_result(spec.id, spec.version, "reference-run-1") is not None
    assert eval_service.get_result(spec.id, spec.version, "reference-run-2") is not None

    snapshot = eval_service.publish_snapshot(spec.id, eval_version=spec.version)
    assert snapshot.sample_count == 2
    assert set(snapshot.source_run_ids) == {"reference-run-1", "reference-run-2"}
