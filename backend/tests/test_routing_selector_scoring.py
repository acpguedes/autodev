"""Tests for the E5-S4 ``score-weighted`` selector stage (backend.routing.selector_scoring).

Covers no-op passthrough behavior (no snapshot, or no weights declared) and
real weighted re-ranking once both are supplied — including the
per-registered-version resolution correctness regression test. Split out of
:mod:`test_routing_selector` to keep both files under the repository's
file-size guideline (mirrors the
:mod:`backend.routing.selector`/:mod:`backend.routing.selector_scoring` split).
Does not duplicate E5-S4's closed eval-to-selection feedback loop
(:mod:`test_routing_feedback_e2e`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agents.manifest import validate_agent_manifest
from backend.agents.registry_v2 import AgentRegistry
from backend.persistence.database import DurableStore
from backend.routing.contract import (
    AgentScoreAggregate,
    RouteConstraints,
    RouteDecision,
    ScoreSnapshot,
    SelectBudget,
    SelectRequest,
)
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


def _agent_manifest(
    agent_id: str,
    *,
    version: str = "1.0.0",
    capabilities: tuple[str, ...] = ("code.implementation",),
    capability_level: str = "primary",
    cost_usd: float = 0.5,
    wall_clock_seconds: int = 60,
    tokens_input: int = 1000,
    tokens_output: int = 500,
    model: str = "provider/model-a",
    reasoning_strategy: str = "react",
) -> dict[str, Any]:
    """Build a raw agent manifest document for selector tests."""
    return {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": agent_id,
        "version": version,
        "hostApi": ">=2.0 <3.0",
        "capabilities": [
            {"id": capability, "version": "1.0.0", "level": capability_level} for capability in capabilities
        ],
        "io": {
            "contract": "acme/selector-io",
            "contractVersion": "1.0.0",
            "input": {"type": "object", "additionalProperties": True},
            "output": {"type": "object", "additionalProperties": True},
        },
        "entrypoint": {"runtime": "python", "ref": "agent_module:Agent"},
        "budgets": {
            "tokens": {"input": tokens_input, "output": tokens_output},
            "costUsd": cost_usd,
            "wallClockSeconds": wall_clock_seconds,
        },
        "policy": {"model": model, "reasoning_strategy": reasoning_strategy},
    }


def _register(registry: AgentRegistry, **kwargs: Any) -> None:
    """Validate and register an agent manifest built by :func:`_agent_manifest`."""
    result = validate_agent_manifest(_agent_manifest(**kwargs))
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="acme/plugin")


def _registry(tmp_path: Path) -> AgentRegistry:
    """Build a fresh :class:`AgentRegistry` bound to a temp sqlite store."""
    store = DurableStore(f"sqlite:///{tmp_path / 'agents.db'}")
    return AgentRegistry(store)


def _select_policy(
    *,
    objective: str = "minimize_cost",
    score_weights: dict[str, float] | None = None,
) -> RoutingPolicy:
    """Build a minimal RoutingPolicy wrapping capability-matching -> cost-aware -> score-weighted."""
    policy = default_routing_policy()
    weights = {"quality": 0.6, "cost": 0.4} if score_weights is None else score_weights
    stages = (
        SelectorCapabilityMatchingStageSpec(require_all=True),
        SelectorCostAwareStageSpec(objective=objective, respect_run_budget=True),
        SelectorScoreWeightedStageSpec(weights=weights),
    )
    return RoutingPolicy(
        schema_version=policy.schema_version,
        id=policy.id,
        version=policy.version,
        host_api=policy.host_api,
        router=policy.router,
        selector=SelectorPolicySpec(pipeline=SelectorPipelineSpec(stages=stages, tie_breaker="lowest_cost")),
    )


def _select_request() -> SelectRequest:
    """Build a minimal SelectRequest around a route decision and an unconstrained budget."""
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


# ---------------------------------------------------------------------------
# Score-weighted stage: no-op passthrough vs. real re-ranking (E5-S4)
# ---------------------------------------------------------------------------


def test_score_weighted_stage_does_not_change_ordering_without_a_snapshot(tmp_path: Path) -> None:
    """The score-weighted stage is a documented no-op when no snapshot is supplied."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/cheap", cost_usd=0.1)
    _register(registry, agent_id="acme/expensive", cost_usd=0.9)

    policy = _select_policy(objective="minimize_cost")
    decision = Selector().select(_select_request(), policy, registry)

    assert decision.agent_id == "acme/cheap"
    assert decision.score_basis == ""


def test_score_weighted_stage_is_a_no_op_when_the_stage_declares_no_weights(tmp_path: Path) -> None:
    """A snapshot is recorded as score_basis but does not reorder candidates when weights={}."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/cheap", cost_usd=0.1)
    _register(registry, agent_id="acme/expensive", cost_usd=0.9)

    policy = _select_policy(objective="minimize_cost", score_weights={})
    snapshot = ScoreSnapshot(schema_version="1.0", snapshot_id="snap-1", scores={"acme/expensive": 1.0})
    decision = Selector().select(_select_request(), policy, registry, snapshot)

    # Still the cheapest candidate — an empty `weights` map is a valid, intentional no-op.
    assert decision.agent_id == "acme/cheap"
    assert decision.score_basis == "snap-1"


def test_score_weighted_stage_blends_a_supplied_snapshot_into_ranking(tmp_path: Path) -> None:
    """With weights configured, a supplied ScoreSnapshot actually re-ranks candidates (E5-S4).

    ``acme/expensive`` is costlier but has a much higher published quality
    score; with weights favoring quality (0.6) over cost (0.4), it outranks
    the cheaper, unscored candidate — overriding the earlier cost-aware
    stage's ``minimize_cost`` objective, per the pipeline's "later stage wins"
    sequential-transform contract.
    """
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/cheap", cost_usd=0.1)
    _register(registry, agent_id="acme/expensive", cost_usd=0.9)

    policy = _select_policy(objective="minimize_cost")
    snapshot = ScoreSnapshot(
        schema_version="1.0",
        snapshot_id="snap-1",
        agent_scores={"acme/expensive": AgentScoreAggregate(quality=1.0, cost_usd=0.9, sample_count=10)},
    )
    decision = Selector().select(_select_request(), policy, registry, snapshot)

    assert decision.agent_id == "acme/expensive"
    assert decision.score_basis == "snap-1"


def test_score_weighted_stage_falls_back_to_the_flat_scores_mapping(tmp_path: Path) -> None:
    """A snapshot with only the flat `scores` mapping (no `agent_scores`) still blends in.

    Backward compatibility with a snapshot constructed with just a bare
    quality scalar per agent id (the pre-E5-S4 minimal shape).
    """
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/cheap", cost_usd=0.1)
    _register(registry, agent_id="acme/expensive", cost_usd=0.9)

    policy = _select_policy(objective="minimize_cost")
    snapshot = ScoreSnapshot(schema_version="1.0", snapshot_id="snap-1", scores={"acme/expensive": 1.0})
    decision = Selector().select(_select_request(), policy, registry, snapshot)

    assert decision.agent_id == "acme/expensive"
    assert decision.score_basis == "snap-1"


def test_score_weighted_stage_resolves_the_correct_aggregate_per_registered_version(tmp_path: Path) -> None:
    """Two registered versions of the same agent_id each blend in their OWN snapshot entry.

    Regression test: an earlier implementation keyed its internal per-candidate
    aggregate lookup by bare ``agent_id`` (not ``(agent_id, version)``), so
    when two versions of the same agent survived the pipeline this far, one
    would silently inherit the other's aggregate instead of its own
    version-specific one.
    """
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/agent-x", version="1.0.0", cost_usd=0.5)
    _register(registry, agent_id="acme/agent-x", version="2.0.0", cost_usd=0.5)

    policy = _select_policy(objective="minimize_cost")
    snapshot = ScoreSnapshot(
        schema_version="1.0",
        snapshot_id="snap-1",
        agent_scores={
            "acme/agent-x@1.0.0": AgentScoreAggregate(quality=0.9, cost_usd=0.5, sample_count=5),
            "acme/agent-x@2.0.0": AgentScoreAggregate(quality=0.1, cost_usd=0.5, sample_count=5),
        },
    )
    decision = Selector().select(_select_request(), policy, registry, snapshot)

    # The higher-quality version (1.0.0) must win — not whichever version the
    # aggregate lookup happened to collide on.
    assert decision.agent_id == "acme/agent-x"
    assert decision.agent_version == "1.0.0"
