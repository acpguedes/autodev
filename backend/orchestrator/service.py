"""Service responsible for coordinating agent executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from backend.agents import (
    Agent,
    AgentContext,
    AgentResult,
    AnalyzerAgent,
    ArchitectAgent,
    CoderAgent,
    DevOpsAgent,
    NavigatorAgent,
    PlannerAgent,
    ValidatorAgent,
)


@dataclass(slots=True)
class HistoryItem:
    """Represents a single conversational turn."""

    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class SessionState:
    """In-memory representation of an orchestration session."""

    session_id: str
    goal: str
    plan: List[str]
    history: List[HistoryItem] = field(default_factory=list)
    artifacts: Dict[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class AgentExecution:
    """Result produced by an agent during orchestration."""

    agent: str
    content: str
    metadata: Mapping[str, Any]


@dataclass(slots=True)
class OrchestratorRun:
    """Aggregate response returned to the API layer."""

    session_id: str
    history: List[HistoryItem]
    results: List[AgentExecution]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "history": [item.to_dict() for item in self.history],
            "results": [
                {"agent": result.agent, "content": result.content, "metadata": dict(result.metadata)}
                for result in self.results
            ],
        }


@dataclass(slots=True)
class PlanSession:
    """Data returned after generating a plan."""

    session_id: str
    goal: str
    plan: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"session_id": self.session_id, "goal": self.goal, "plan": list(self.plan)}


@dataclass(slots=True)
class OrchestratorConfig:
    """Configuration values for the orchestrator service."""

    agent_order: Iterable[str] = (
        "navigator",
        "analyzer",
        "architect",
        "coder",
        "devops",
        "validator",
    )


class AgentGraphState(TypedDict):
    """State propagated through the LangGraph workflow."""

    context: AgentContext
    results: List["AgentExecution"]


class OrchestratorService:
    """Coordinate agent execution for a session."""

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        agents: Mapping[str, Agent] | None = None,
    ) -> None:
        self._config = config or OrchestratorConfig()
        self._agents = self._build_default_agents()
        if agents:
            self._agents.update(agents)
        self._sessions: Dict[str, SessionState] = {}
        self._graph = self._compile_graph()

    def create_plan(self, goal: str) -> PlanSession:
        planner: PlannerAgent = self._require_agent("planner")  # type: ignore[assignment]
        session_id = str(uuid4())
        context = AgentContext(session_id=session_id, goal=goal)
        plan_result = planner.run(context)
        plan_steps = list(plan_result.metadata.get("steps", []))
        if not plan_steps:
            plan_steps = []
            for line in plan_result.content.splitlines():
                stripped_line = line.strip()
                if not stripped_line or not stripped_line.startswith("-"):
                    continue
                cleaned_step = stripped_line.lstrip("- ").strip()
                if cleaned_step:
                    plan_steps.append(cleaned_step)

        state = SessionState(session_id=session_id, goal=goal, plan=plan_steps)
        state.artifacts[planner.name] = plan_result.metadata
        self._sessions[session_id] = state
        return PlanSession(session_id=session_id, goal=goal, plan=plan_steps)

    def handle_message(self, session_id: str, message: str) -> OrchestratorRun:
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(f"Unknown session_id: {session_id}")

        user_entry = HistoryItem(role="user", content=message)
        context = AgentContext(
            session_id=session_id,
            goal=state.goal,
            history=[entry.to_dict() for entry in state.history] + [user_entry.to_dict()],
            artifacts={name: dict(meta) for name, meta in state.artifacts.items()},
        )

        initial_state: AgentGraphState = {"context": context, "results": []}
        final_state = self._graph.invoke(initial_state)
        final_context = final_state["context"]
        results = list(final_state["results"])

        state.history = [HistoryItem(**item) for item in final_context.history]
        state.artifacts = self._clone_artifacts(final_context.artifacts)

        return OrchestratorRun(session_id=session_id, history=list(state.history), results=results)

    def get_plan(self, session_id: str) -> PlanSession:
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return PlanSession(session_id=state.session_id, goal=state.goal, plan=list(state.plan))

    def _require_agent(self, name: str) -> Agent:
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' has not been registered")
        return self._agents[name]

    def _build_default_agents(self) -> Dict[str, Agent]:
        return {
            "planner": PlannerAgent(),
            "navigator": NavigatorAgent(),
            "analyzer": AnalyzerAgent(),
            "architect": ArchitectAgent(),
            "coder": CoderAgent(),
            "devops": DevOpsAgent(),
            "validator": ValidatorAgent(),
        }

    def _compile_graph(self) -> Any:
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

    def _make_agent_node(self, agent_name: str):
        def node(state: AgentGraphState) -> AgentGraphState:
            agent = self._require_agent(agent_name)
            context = state["context"]
            agent_result: AgentResult = agent.run(context)
            execution = AgentExecution(
                agent=agent.name,
                content=agent_result.content,
                metadata=agent_result.metadata,
            )
            next_context = context.with_artifact(agent.name, agent_result.metadata)
            next_context = next_context.with_message(agent.name, agent_result.content)
            next_results = list(state["results"])
            next_results.append(execution)
            return {"context": next_context, "results": next_results}

        return node

    def _clone_artifacts(self, artifacts: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
        cloned: Dict[str, Mapping[str, Any]] = {}
        for name, value in artifacts.items():
            if isinstance(value, MutableMapping):
                cloned[name] = dict(value)
            else:
                cloned[name] = value
        return cloned


__all__ = [
    "AgentExecution",
    "HistoryItem",
    "OrchestratorConfig",
    "OrchestratorRun",
    "OrchestratorService",
    "PlanSession",
    "SessionState",
]
