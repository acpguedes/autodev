"""Agent registry and LangGraph chat-workflow construction for the orchestrator (E47-S5)."""

from __future__ import annotations

from typing import Any, Dict

from langgraph.graph import END, StateGraph

from backend.agents import (
    Agent,
    AgentResult,
    AnalyzerAgent,
    ArchitectAgent,
    CoderAgent,
    DevOpsAgent,
    NavigatorAgent,
    PlannerAgent,
    ResponderAgent,
    ValidatorAgent,
)
from backend.observability.tracing import trace_run_step
from backend.orchestrator.service import events
from backend.orchestrator.service._shared import OrchestratorState
from backend.orchestrator.service.models import (
    AgentExecution,
    AgentGraphState,
    RunStep,
    StepStatus,
    _TIMELINE_OUTPUT_CHAR_CAP,
)
from backend.persistence.tenancy import DEFAULT_TENANT_ID


class GraphMixin(OrchestratorState):
    """Agent registration/lookup and the linear per-message LangGraph workflow."""

    def _require_agent(self, name: str) -> Agent:
        """Fetch a registered agent by name.

        Raises:
            KeyError: If no agent named ``name`` is registered.
        """
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' has not been registered")
        return self._agents[name]

    def _build_default_agents(self) -> Dict[str, Agent]:
        """Build the built-in agent set, merged with any discovered plugin agents."""
        agents: Dict[str, Agent] = {
            "planner": PlannerAgent(),
            "navigator": NavigatorAgent(project_root=self._project_root),
            "analyzer": AnalyzerAgent(),
            "architect": ArchitectAgent(),
            "coder": CoderAgent(),
            "devops": DevOpsAgent(),
            "validator": ValidatorAgent(),
            "responder": ResponderAgent(),
        }
        try:
            from backend.agents.registry import discover_agents

            for n, a in discover_agents(self._project_root).items():
                agents.setdefault(n, a)
        except Exception:
            pass
        return agents

    def _compile_graph(self) -> Any:
        """Compile the LangGraph workflow from the configured agent order."""
        workflow = StateGraph(AgentGraphState)
        order = list(self._config.agent_order)
        for agent_name in order:
            workflow.add_node(agent_name, self._make_agent_node(agent_name))

        if not order:
            return workflow.compile()

        workflow.set_entry_point(order[0])
        for current, nxt in zip(order, order[1:]):
            workflow.add_edge(current, nxt)
        workflow.add_edge(order[-1], END)
        return workflow.compile()

    def _make_agent_node(self, agent_name: str) -> Any:
        """Build a LangGraph node function that runs the named agent."""

        def node(state: AgentGraphState) -> AgentGraphState:
            """Run the wrapped agent once and append its result to the graph state."""
            agent = self._require_agent(agent_name)
            context = state["context"]
            started_at = self._timestamp()
            with trace_run_step(
                run_id=state["run_id"],
                step_id=agent_name,
                agent=agent.name,
                status=StepStatus.COMPLETED,
                tenant_id=DEFAULT_TENANT_ID,
            ):
                agent_result: AgentResult = agent.run(context)
            execution = AgentExecution(
                agent=agent.name,
                content=agent_result.content,
                metadata=agent_result.metadata,
            )
            completed_at = self._timestamp()
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
            self._emit_agent_timeline_event(
                run_id=state["run_id"],
                tenant_id=state.get("tenant_id", DEFAULT_TENANT_ID),
                agent_name=agent_name,
                output=agent_result.content,
            )
            return {
                "context": next_context,
                "results": next_results,
                "steps": next_steps,
                "current_state": "completed",
                "run_id": state["run_id"],
                "tenant_id": state.get("tenant_id", DEFAULT_TENANT_ID),
            }

        return node

    def _emit_agent_timeline_event(
        self, *, run_id: str, tenant_id: str, agent_name: str, output: str
    ) -> None:
        """Emit a live ``run.timeline.*`` event for one completed chat-graph agent (E43-S6).

        Reuses the exact mapping/event-type/schema
        ``task_dispatch._render_dispatch_records`` already emits for the
        "Run plan" pipeline
        (:func:`backend.api.timeline_roles.timeline_event_type_for_agent_role`,
        :class:`~backend.events.catalog.RunTimelineStepData`) so
        ``RunTimelinePanel``'s existing live subscription -- previously fed
        by nothing during a Chat turn, since only task dispatch emitted
        these -- now shows real per-agent progress as the turn runs, not
        only the final message once everything has already finished.
        Only the roles the timeline maps (planner/navigator/analyzer/coder/
        validator) emit; architect/devops/responder are intentionally left
        off the four-stage timeline, matching the existing mapping.

        Args:
            run_id: The run this agent step belongs to.
            tenant_id: Tenant the run belongs to.
            agent_name: The agent role that just completed (e.g. ``"navigator"``).
            output: The agent's real text output for this step.
        """
        from backend.api.timeline_roles import timeline_event_type_for_agent_role  # noqa: PLC0415

        timeline_event_type = timeline_event_type_for_agent_role(agent_name)
        if timeline_event_type is None:
            return
        events.emit_event(
            timeline_event_type,
            tenant_id=tenant_id,
            partition_key=run_id,
            data={
                "stepKey": agent_name,
                "actorRole": agent_name,
                "status": "completed",
                "output": output[:_TIMELINE_OUTPUT_CHAR_CAP],
            },
            subject={"runId": run_id},
        )


__all__ = ["GraphMixin"]
