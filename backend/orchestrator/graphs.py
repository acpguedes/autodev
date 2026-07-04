"""LangGraph builders parameterised by agent order and RunType.

This module is STANDALONE — it is not wired into the default ``/chat`` path.

Key exports:
- ``build_conditional_graph`` — compile a LangGraph from an explicit order list.
- ``build_graph_for_run_type`` — convenience wrapper via ``RunTypeRouter``.
"""

from __future__ import annotations

import datetime
from typing import Any, Mapping

from langgraph.graph import END, StateGraph

from backend.agents.base import Agent, AgentContext, AgentResult
from backend.orchestrator.routing import RunTypeRouter
from backend.orchestrator.service import (
    AgentExecution,
    AgentGraphState,
    RunStep,
    RunType,
    StepStatus,
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _make_node(agent_name: str, agent: Agent):
    """Build a LangGraph node function for *agent*."""

    def node(state: AgentGraphState) -> AgentGraphState:
        context: AgentContext = state["context"]
        started_at = _now()
        agent_result: AgentResult = agent.run(context)
        execution = AgentExecution(
            agent=agent.name,
            content=agent_result.content,
            metadata=agent_result.metadata,
        )
        completed_at = _now()
        next_context = context.with_artifact(agent.name, agent_result.metadata)
        next_context = next_context.with_message(agent.name, agent_result.content)
        next_results = list(state["results"])
        next_results.append(execution)
        next_steps = list(state["steps"])
        next_steps.append(
            RunStep(
                step_key=agent_name,
                agent=agent.name,
                status=StepStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
            )
        )
        return AgentGraphState(
            context=next_context,
            results=next_results,
            steps=next_steps,
            current_state=agent_name,
            run_id=state["run_id"],
        )

    return node


def build_conditional_graph(
    agents: Mapping[str, Agent],
    order: list[str],
) -> Any:
    """Compile a LangGraph from an explicit agent order.

    Mirrors ``OrchestratorService._compile_graph`` but is parameterised so
    callers can supply any subset of agents and any order.

    Parameters
    ----------
    agents:
        Mapping of agent name -> Agent instance.  Only names in *order* need
        to be present.
    order:
        Ordered list of agent names to include in the graph.

    Returns
    -------
    A compiled LangGraph invokeable with an ``AgentGraphState`` dict.
    """
    if not order:
        raise ValueError("order must contain at least one agent name")

    for name in order:
        if name not in agents:
            raise KeyError(
                f"Agent {name!r} is in order but not in agents mapping. "
                f"Available: {sorted(agents)}"
            )

    workflow: StateGraph = StateGraph(AgentGraphState)  # type: ignore[type-arg]

    for agent_name in order:
        workflow.add_node(agent_name, _make_node(agent_name, agents[agent_name]))

    workflow.set_entry_point(order[0])
    for current, nxt in zip(order, order[1:]):
        workflow.add_edge(current, nxt)
    workflow.add_edge(order[-1], END)

    return workflow.compile()


def build_graph_for_run_type(
    agents: Mapping[str, Agent],
    run_type: RunType,
    router: RunTypeRouter | None = None,
) -> Any:
    """Convenience wrapper: resolve the order from *run_type* then build the graph.

    Agents not present in *agents* but listed in the router order are silently
    skipped so the graph degrades gracefully.
    """
    effective_router = router if router is not None else RunTypeRouter()
    requested_order = effective_router.order_for(run_type)
    available_order = [name for name in requested_order if name in agents]
    if not available_order:
        raise ValueError(
            f"No agents available for run type {run_type!r}. "
            f"Requested: {requested_order}. Available: {sorted(agents)}"
        )
    return build_conditional_graph(agents, available_order)


__all__ = [
    "build_conditional_graph",
    "build_graph_for_run_type",
]
