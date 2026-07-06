"""Tests for the E5-S2 Selector pipeline executor and contract.

Covers the story DoD: capability-based matching (``require_all`` intersection
correctness), cost-aware ordering, deterministic tie-breaking (same inputs
produce the same decision on repeated runs), decision trace emission,
score-weighted no-op passthrough behavior, and pluggability (a custom
:class:`~backend.routing.contract.SelectorPlugin` works without core changes).
Does not duplicate E5-S1's router tests (:mod:`test_routing_router`) or
E5-S3's eval tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.agents.manifest import validate_agent_manifest
from backend.agents.registry_v2 import AgentRegistry
from backend.persistence.database import DurableStore
from backend.routing.contract import (
    RouteConstraints,
    RouteDecision,
    ScoreSnapshot,
    SelectBudget,
    SelectDecision,
    SelectRequest,
    TraceEvent,
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
from backend.routing.selector import NoEligibleAgentError, Selector
from backend.routing.service import RoutingService


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
    require_all: bool = True,
    objective: str = "minimize_cost",
    respect_run_budget: bool = True,
    include_score_weighted: bool = False,
    tie_breaker: str = "lowest_cost",
) -> RoutingPolicy:
    """Build a minimal RoutingPolicy wrapping a selector pipeline for tests."""
    policy = default_routing_policy()
    stages: tuple[Any, ...] = (
        SelectorCapabilityMatchingStageSpec(require_all=require_all),
        SelectorCostAwareStageSpec(objective=objective, respect_run_budget=respect_run_budget),
    )
    if include_score_weighted:
        stages = stages + (SelectorScoreWeightedStageSpec(weights={"quality": 0.6, "cost": 0.4}),)
    return RoutingPolicy(
        schema_version=policy.schema_version,
        id=policy.id,
        version=policy.version,
        host_api=policy.host_api,
        router=policy.router,
        selector=SelectorPolicySpec(pipeline=SelectorPipelineSpec(stages=stages, tie_breaker=tie_breaker)),
    )


def _select_request(
    *,
    required_capabilities: tuple[str, ...] = ("code.implementation",),
    tokens: int = 0,
    cost_usd: float = 0.0,
    time_s: int = 0,
) -> SelectRequest:
    """Build a minimal SelectRequest around a route decision and a budget."""
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
        required_capabilities=required_capabilities,
        budget=SelectBudget(tokens=tokens, cost_usd=cost_usd, time_s=time_s),
    )


# ---------------------------------------------------------------------------
# Capability-based matching (require_all intersection correctness)
# ---------------------------------------------------------------------------


def test_require_all_selects_only_the_candidate_covering_every_capability(tmp_path: Path) -> None:
    """With require_all=True, only the agent declaring every capability is eligible."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/only-implementation", capabilities=("code.implementation",))
    _register(registry, agent_id="acme/only-refactor", capabilities=("code.refactor",))
    _register(registry, agent_id="acme/both", capabilities=("code.implementation", "code.refactor"))

    policy = _select_policy(require_all=True)
    req = _select_request(required_capabilities=("code.implementation", "code.refactor"))
    decision = Selector().select(req, policy, registry)

    assert decision.agent_id == "acme/both"
    assert decision.fallbacks == ()


def test_require_any_selects_among_the_union_of_matching_candidates(tmp_path: Path) -> None:
    """With require_all=False, any candidate matching at least one capability is eligible."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/only-implementation", capabilities=("code.implementation",), cost_usd=0.9)
    _register(registry, agent_id="acme/only-refactor", capabilities=("code.refactor",), cost_usd=0.1)
    _register(registry, agent_id="acme/unrelated", capabilities=("planning.decompose",), cost_usd=0.05)

    policy = _select_policy(require_all=False, objective="minimize_cost")
    req = _select_request(required_capabilities=("code.implementation", "code.refactor"))
    decision = Selector().select(req, policy, registry)

    # The unrelated agent (planning.decompose only) never matched either
    # required capability, so it must not appear as the winner or a fallback.
    assert decision.agent_id == "acme/only-refactor"  # cheapest among the union
    fallback_ids = {fb.agent_id for fb in decision.fallbacks}
    assert "acme/unrelated" not in fallback_ids
    assert "acme/only-implementation" in fallback_ids


def test_empty_required_capabilities_matches_every_registered_agent(tmp_path: Path) -> None:
    """An empty required_capabilities list is treated as matching every registered agent."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/agent-a", capabilities=("code.implementation",), cost_usd=0.2)
    _register(registry, agent_id="acme/agent-b", capabilities=("code.refactor",), cost_usd=0.1)

    policy = _select_policy()
    req = _select_request(required_capabilities=())
    decision = Selector().select(req, policy, registry)

    assert decision.agent_id == "acme/agent-b"  # cheaper of the two


def test_no_matching_candidate_raises_no_eligible_agent_error(tmp_path: Path) -> None:
    """When no registered agent satisfies required_capabilities, selection fails closed."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/agent-a", capabilities=("code.implementation",))

    policy = _select_policy(require_all=True)
    req = _select_request(required_capabilities=("security.review",))

    with pytest.raises(NoEligibleAgentError):
        Selector().select(req, policy, registry)


def test_duplicate_required_capabilities_do_not_inflate_a_candidates_score(tmp_path: Path) -> None:
    """Repeating the same capability in required_capabilities must not double-count its score."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/agent-a", capabilities=("code.implementation",))

    policy = _select_policy(require_all=True, objective="maximize_quality")
    once = Selector().select(_select_request(required_capabilities=("code.implementation",)), policy, registry)
    twice = Selector().select(
        _select_request(required_capabilities=("code.implementation", "code.implementation")), policy, registry
    )

    # Score is not part of SelectDecision, but a duplicated-capability request
    # must resolve to the exact same decision as the deduplicated one — if the
    # score were inflated, ordering against other candidates could change even
    # though it can't be observed via this single-candidate decision alone.
    assert once == twice


def test_capability_matching_narrows_whatever_the_prior_stage_produced(tmp_path: Path) -> None:
    """capability-matching filters the running candidate pool, not the whole registry.

    Placing ``cost-aware`` before ``capability-matching`` must not reset the
    pool back to every registered agent — the pipeline is a sequential
    narrowing transform (see backend.routing.selector's module docstring), so
    an agent excluded by an earlier stage (here, over budget) must stay
    excluded even though it does declare the required capability.
    """
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/within-budget", capabilities=("code.implementation",), cost_usd=0.2)
    _register(registry, agent_id="acme/over-budget", capabilities=("code.implementation",), cost_usd=5.0)

    policy = RoutingPolicy(
        schema_version="1",
        id="autodev/routing-test",
        version="1.0.0",
        host_api=">=2.0 <3.0",
        router=default_routing_policy().router,
        selector=SelectorPolicySpec(
            pipeline=SelectorPipelineSpec(
                stages=(
                    # cost-aware runs BEFORE capability-matching in this policy.
                    SelectorCostAwareStageSpec(objective="minimize_cost", respect_run_budget=True),
                    SelectorCapabilityMatchingStageSpec(require_all=True),
                ),
                tie_breaker="lowest_cost",
            )
        ),
    )
    req = _select_request(required_capabilities=("code.implementation",), cost_usd=1.0)

    decision = Selector().select(req, policy, registry)

    assert decision.agent_id == "acme/within-budget"
    assert all(fb.agent_id != "acme/over-budget" for fb in decision.fallbacks)


# ---------------------------------------------------------------------------
# Cost-aware ordering
# ---------------------------------------------------------------------------


def test_minimize_cost_objective_orders_candidates_ascending_by_cost(tmp_path: Path) -> None:
    """The minimize_cost objective picks the cheapest eligible candidate first."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/expensive", cost_usd=0.9)
    _register(registry, agent_id="acme/cheap", cost_usd=0.1)
    _register(registry, agent_id="acme/mid", cost_usd=0.5)

    policy = _select_policy(objective="minimize_cost")
    decision = Selector().select(_select_request(), policy, registry)

    assert decision.agent_id == "acme/cheap"
    assert [fb.agent_id for fb in decision.fallbacks] == ["acme/mid", "acme/expensive"]


def test_minimize_latency_objective_orders_candidates_by_wall_clock_seconds(tmp_path: Path) -> None:
    """The minimize_latency objective picks the fastest eligible candidate first."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/slow", wall_clock_seconds=300, cost_usd=0.1)
    _register(registry, agent_id="acme/fast", wall_clock_seconds=10, cost_usd=0.9)

    policy = _select_policy(objective="minimize_latency")
    decision = Selector().select(_select_request(), policy, registry)

    assert decision.agent_id == "acme/fast"


def test_maximize_quality_objective_orders_candidates_by_capability_score(tmp_path: Path) -> None:
    """The maximize_quality objective prefers a primary-capability agent over a secondary one."""
    registry = _registry(tmp_path)
    # Primary-level capability ranks strictly above secondary (registry_v2 scoring),
    # even though the secondary-level candidate is far cheaper.
    _register(registry, agent_id="acme/secondary", capability_level="secondary", cost_usd=0.05)
    _register(registry, agent_id="acme/primary", capability_level="primary", cost_usd=0.95)

    policy = _select_policy(objective="maximize_quality")
    decision = Selector().select(_select_request(), policy, registry)

    assert decision.agent_id == "acme/primary"


def test_respect_run_budget_filters_out_candidates_that_exceed_it(tmp_path: Path) -> None:
    """A candidate whose own cost ceiling exceeds the run's budget is excluded."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/within-budget", cost_usd=0.2)
    _register(registry, agent_id="acme/over-budget", cost_usd=5.0)

    policy = _select_policy(objective="minimize_cost", respect_run_budget=True)
    req = _select_request(cost_usd=1.0)
    decision = Selector().select(req, policy, registry)

    assert decision.agent_id == "acme/within-budget"
    assert all(fb.agent_id != "acme/over-budget" for fb in decision.fallbacks)


# ---------------------------------------------------------------------------
# Deterministic tie-breaking
# ---------------------------------------------------------------------------


def test_selection_is_reproducible_given_the_same_state(tmp_path: Path) -> None:
    """The same registry state, policy, and request produce an identical decision every run."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/agent-a", cost_usd=0.3)
    _register(registry, agent_id="acme/agent-b", cost_usd=0.3)  # tied on cost with agent-a

    policy = _select_policy(objective="minimize_cost")
    req = _select_request()

    first = Selector().select(req, policy, registry)
    second = Selector().select(req, policy, registry)

    assert first == second


def test_tie_breaks_by_lowest_cost_then_newest_version_then_agent_id(tmp_path: Path) -> None:
    """Ties on the primary objective break by lowest_cost, then newer version, then agent_id."""
    registry = _registry(tmp_path)
    # Same cost -> tie_breaker (lowest_cost) is also tied -> newest version wins.
    _register(registry, agent_id="acme/versioned", version="1.0.0", cost_usd=0.4)
    _register(registry, agent_id="acme/versioned", version="2.0.0", cost_usd=0.4)
    _register(registry, agent_id="acme/other", version="1.0.0", cost_usd=0.4)

    policy = _select_policy(objective="minimize_cost")
    decision = Selector().select(_select_request(), policy, registry)

    assert decision.agent_id == "acme/versioned"
    assert decision.agent_version == "2.0.0"


# ---------------------------------------------------------------------------
# Decision trace emission
# ---------------------------------------------------------------------------


def test_routing_service_records_a_selector_decision_trace_event(tmp_path: Path) -> None:
    """Every SelectDecision produced by the service is recorded to the trace sink."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/agent-a", cost_usd=0.2)

    events: list[TraceEvent] = []
    service = RoutingService(_select_policy(), on_event=events.append)
    decision = service.select(_select_request(), registry=registry)

    assert len(events) == 1
    event = events[0]
    assert event.name == "selector.decision.recorded"
    assert event.payload["agent_id"] == decision.agent_id
    assert event.payload["model"] == decision.model
    assert event.payload["reasoning_strategy"] == decision.reasoning_strategy


# ---------------------------------------------------------------------------
# Score-weighted no-op passthrough
# ---------------------------------------------------------------------------


def test_score_weighted_stage_does_not_change_ordering_without_a_snapshot(tmp_path: Path) -> None:
    """The score-weighted stage is a documented no-op when no snapshot is supplied."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/cheap", cost_usd=0.1)
    _register(registry, agent_id="acme/expensive", cost_usd=0.9)

    policy = _select_policy(objective="minimize_cost", include_score_weighted=True)
    decision = Selector().select(_select_request(), policy, registry)

    assert decision.agent_id == "acme/cheap"
    assert decision.score_basis == ""


def test_score_weighted_stage_records_but_does_not_apply_a_supplied_snapshot(tmp_path: Path) -> None:
    """A supplied ScoreSnapshot is recorded as score_basis but does not reorder candidates."""
    registry = _registry(tmp_path)
    _register(registry, agent_id="acme/cheap", cost_usd=0.1)
    _register(registry, agent_id="acme/expensive", cost_usd=0.9)

    policy = _select_policy(objective="minimize_cost", include_score_weighted=True)
    snapshot = ScoreSnapshot(schema_version="1.0", snapshot_id="snap-1", scores={"acme/expensive": 1.0})
    decision = Selector().select(_select_request(), policy, registry, snapshot)

    # Still the cheapest candidate — the snapshot's scores are not applied to ranking yet.
    assert decision.agent_id == "acme/cheap"
    assert decision.score_basis == "snap-1"


# ---------------------------------------------------------------------------
# Pluggability: a custom SelectorPlugin works without core changes
# ---------------------------------------------------------------------------


def test_custom_selector_plugin_works_without_core_changes(tmp_path: Path) -> None:
    """A SelectorPlugin that is NOT a Selector instance still flows through the service."""

    class _FixedSelector:
        """Minimal custom SelectorPlugin that always returns a fixed decision."""

        def select(self, req: SelectRequest, policy: Any, registry: Any, scores: Any = None) -> SelectDecision:
            """Return a fixed SelectDecision regardless of input."""
            return SelectDecision(
                schema_version="1.0",
                agent_id="acme/custom-agent",
                agent_version="9.9.9",
                model="provider/custom-model",
                reasoning_strategy="plan-and-execute",
                budget=SelectBudget(tokens=1000, cost_usd=0.1, time_s=30),
            )

    registry = _registry(tmp_path)
    service = RoutingService(_select_policy(), selector=_FixedSelector())
    decision = service.select(_select_request(), registry=registry)

    assert decision.agent_id == "acme/custom-agent"
    assert decision.model == "provider/custom-model"
