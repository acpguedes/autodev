"""Tests for U7 orchestrator routing (routing.py + graphs.py).

Assertions:
- RunTypeRouter maps each RunType to the correct agent order.
- RunTypeRouter.order_for falls back to the full order for unmapped types.
- build_conditional_graph raises on empty order and on missing agent.
- build_graph_for_run_type compiles a graph for VALIDATION_ONLY using real
  default agents (stub LLM) and the invoked graph yields results only for
  the agents in that subset.
- SupervisorPolicy cursor advances correctly and returns None after exhaustion.
"""

from __future__ import annotations

import pytest

from backend.orchestrator.routing import RunTypeRouter, SupervisorPolicy
from backend.orchestrator.service import AgentGraphState, RunType


# ---------------------------------------------------------------------------
# RunTypeRouter mappings
# ---------------------------------------------------------------------------


def test_route_documentation_update() -> None:
    """``DOCUMENTATION_UPDATE`` routes through navigator, analyzer, and responder."""
    router = RunTypeRouter()
    order = router.order_for(RunType.DOCUMENTATION_UPDATE)
    assert order == ["navigator", "analyzer", "responder"]


def test_route_validation_only() -> None:
    """``VALIDATION_ONLY`` routes through navigator, validator, and responder."""
    router = RunTypeRouter()
    order = router.order_for(RunType.VALIDATION_ONLY)
    assert order == ["navigator", "validator", "responder"]


def test_route_devops_change() -> None:
    """``DEVOPS_CHANGE`` routes through navigator, analyzer, devops, and responder."""
    router = RunTypeRouter()
    order = router.order_for(RunType.DEVOPS_CHANGE)
    assert order == ["navigator", "analyzer", "devops", "responder"]


def test_route_existing_repo_change_is_full_order() -> None:
    """``EXISTING_REPO_CHANGE`` routes through the full default agent order."""
    router = RunTypeRouter()
    full = ["navigator", "analyzer", "architect", "coder", "devops", "validator", "responder"]
    assert router.order_for(RunType.EXISTING_REPO_CHANGE) == full


def test_route_unknown_type_falls_back_to_full_order() -> None:
    """Any RunType not explicitly mapped should yield the full default order."""
    full = ["navigator", "analyzer", "architect", "coder", "devops", "validator", "responder"]
    custom_router = RunTypeRouter(route_map={RunType.DOCUMENTATION_UPDATE: ["navigator"]})
    # VALIDATION_ONLY is not in the custom map → falls back to _FULL_ORDER.
    assert custom_router.order_for(RunType.VALIDATION_ONLY) == full


def test_all_routes_returns_dict() -> None:
    """``all_routes()`` returns a dict keyed by run type, including ``VALIDATION_ONLY``."""
    router = RunTypeRouter()
    routes = router.all_routes()
    assert isinstance(routes, dict)
    assert RunType.VALIDATION_ONLY in routes


# ---------------------------------------------------------------------------
# SupervisorPolicy
# ---------------------------------------------------------------------------


def test_supervisor_policy_advances() -> None:
    """Cursor should advance through order and return None after exhaustion."""

    dummy_state: AgentGraphState = {
        "context": None,  # type: ignore[typeddict-item]
        "results": [],
        "steps": [],
        "current_state": "start",
        "run_id": "test-run",
    }
    policy = SupervisorPolicy(order=["navigator", "validator", "responder"])
    assert policy.next_agent(dummy_state) == "navigator"
    assert policy.next_agent(dummy_state) == "validator"
    assert policy.next_agent(dummy_state) == "responder"
    assert policy.next_agent(dummy_state) is None


def test_supervisor_policy_reset() -> None:
    """Resetting the policy restarts its cursor from the beginning of the order."""
    dummy_state: AgentGraphState = {
        "context": None,  # type: ignore[typeddict-item]
        "results": [],
        "steps": [],
        "current_state": "start",
        "run_id": "test-run",
    }
    policy = SupervisorPolicy(order=["navigator"])
    policy.next_agent(dummy_state)
    assert policy.next_agent(dummy_state) is None
    policy.reset()
    assert policy.next_agent(dummy_state) == "navigator"


# ---------------------------------------------------------------------------
# build_conditional_graph — error cases
# ---------------------------------------------------------------------------


def test_build_conditional_graph_raises_on_empty_order() -> None:
    """Building a graph with an empty agent order raises ``ValueError``."""
    from backend.orchestrator.graphs import build_conditional_graph

    with pytest.raises(ValueError, match="at least one"):
        build_conditional_graph({}, [])


def test_build_conditional_graph_raises_on_missing_agent() -> None:
    """Building a graph with an order referencing an unregistered agent raises ``KeyError``."""
    from backend.orchestrator.graphs import build_conditional_graph

    with pytest.raises(KeyError, match="navigator"):
        build_conditional_graph({}, ["navigator"])


# ---------------------------------------------------------------------------
# build_graph_for_run_type — integration with real default agents (stub LLM)
# ---------------------------------------------------------------------------


def test_build_graph_for_validation_only_runs() -> None:
    """Compile a VALIDATION_ONLY graph and invoke it; only the subset agents run."""
    from backend.orchestrator.graphs import build_graph_for_run_type
    from backend.orchestrator.service import AgentContext, OrchestratorService

    # Pull the real default agents from the service (they use fallback_result
    # when no LLM is configured, so no API key is needed).
    svc = OrchestratorService()
    agents = svc._agents  # type: ignore[attr-defined]

    graph = build_graph_for_run_type(agents, RunType.VALIDATION_ONLY)
    assert graph is not None

    initial_context = AgentContext(
        session_id="test-u7",
        goal="Validate changes",
        user_request="Run validation only",
        history=[],
    )
    initial_state: AgentGraphState = {
        "context": initial_context,
        "results": [],
        "steps": [],
        "current_state": "start",
        "run_id": "test-run",
    }

    final_state: AgentGraphState = graph.invoke(initial_state)

    agent_names_run = [step.agent for step in final_state["steps"]]
    # Must contain exactly the VALIDATION_ONLY subset.
    assert set(agent_names_run) == {"navigator", "validator", "responder"}
    # Must NOT contain full-order-only agents.
    assert "architect" not in agent_names_run
    assert "coder" not in agent_names_run
