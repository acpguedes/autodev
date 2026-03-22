"""Service responsible for coordinating agent executions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, TypedDict
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
from backend.persistence import DurableStore, get_store


@dataclass(slots=True)
class HistoryItem:
    """Represents a single conversational turn."""

    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class AgentExecution:
    """Result produced by an agent during orchestration."""

    agent: str
    content: str
    metadata: Mapping[str, Any]


@dataclass(slots=True)
class OrchestratorRun:
    """Aggregate response returned to the API layer."""

    run_id: str
    session_id: str
    status: str
    history: List[HistoryItem]
    results: List[AgentExecution]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
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
    status: str = "drafting_plan"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "goal": self.goal,
            "plan": list(self.plan),
            "status": self.status,
        }


@dataclass(slots=True)
class SessionSummary:
    """Session details exposed by the API."""

    session_id: str
    goal: str
    plan: List[str]
    status: str
    history: List[HistoryItem]


@dataclass(slots=True)
class RunSummary:
    """Stored run details for history endpoints."""

    run_id: str
    session_id: str
    status: str
    trigger_message: str
    created_at: str
    results: List[AgentExecution]


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
    results: List[AgentExecution]


class OrchestratorService:
    """Coordinate agent execution for a durable session."""

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        agents: Mapping[str, Agent] | None = None,
        store: DurableStore | None = None,
    ) -> None:
        self._config = config or OrchestratorConfig()
        self._agents = self._build_default_agents()
        if agents:
            self._agents.update(agents)
        self._store = store or get_store()
        self._graph = self._compile_graph()

    def create_plan(self, goal: str) -> PlanSession:
        planner: PlannerAgent = self._require_agent("planner")  # type: ignore[assignment]
        session_id = str(uuid4())
        context = AgentContext(session_id=session_id, goal=goal)
        plan_result = planner.run(context)
        plan_steps = self._extract_plan_steps(plan_result)
        status = "awaiting_input"

        self._store.create_session(
            session_id=session_id,
            goal=goal,
            plan=plan_steps,
            artifacts={planner.name: dict(plan_result.metadata)},
        )

        return PlanSession(session_id=session_id, goal=goal, plan=plan_steps, status=status)

    def handle_message(self, session_id: str, message: str) -> OrchestratorRun:
        session_record = self._store.get_session(session_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")

        history = [
            HistoryItem(role=record["role"], content=record["content"])
            for record in self._store.list_messages(session_id)
        ]
        user_entry = HistoryItem(role="user", content=message)
        context = AgentContext(
            session_id=session_id,
            goal=session_record["goal"],
            history=[item.to_dict() for item in history] + [user_entry.to_dict()],
            artifacts=dict(session_record["artifacts"] or {}),
        )

        initial_state: AgentGraphState = {"context": context, "results": []}
        final_state = self._graph.invoke(initial_state)
        final_context = final_state["context"]
        results = list(final_state["results"])
        run_id = str(uuid4())

        self._store.create_run(
            run_id=run_id,
            session_id=session_id,
            status="completed",
            trigger_message=message,
            results=[
                {
                    "agent": result.agent,
                    "content": result.content,
                    "metadata": dict(result.metadata),
                }
                for result in results
            ],
        )

        next_history = [HistoryItem(**item) for item in final_context.history]
        self._store.append_messages(
            session_id,
            run_id,
            [item.to_dict() for item in next_history],
        )
        self._store.update_session_artifacts(session_id, self._clone_artifacts(final_context.artifacts))

        return OrchestratorRun(
            run_id=run_id,
            session_id=session_id,
            status="completed",
            history=next_history,
            results=results,
        )

    def get_plan(self, session_id: str) -> PlanSession:
        state = self._store.get_session(session_id)
        if state is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return PlanSession(
            session_id=state["id"],
            goal=state["goal"],
            plan=list(state["plan"] or []),
            status="awaiting_input",
        )

    def list_sessions(self) -> List[SessionSummary]:
        return [self._build_session_summary(record) for record in self._store.list_sessions()]

    def get_session(self, session_id: str) -> SessionSummary:
        record = self._store.get_session(session_id)
        if record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return self._build_session_summary(record)

    def list_runs(self, session_id: str) -> List[RunSummary]:
        session_record = self._store.get_session(session_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return [self._build_run_summary(record) for record in self._store.list_runs(session_id)]

    def _build_session_summary(self, record: dict[str, Any]) -> SessionSummary:
        history = [
            HistoryItem(role=item["role"], content=item["content"])
            for item in self._store.list_messages(record["id"])
        ]
        return SessionSummary(
            session_id=record["id"],
            goal=record["goal"],
            plan=list(record["plan"] or []),
            status="awaiting_input",
            history=history,
        )

    def _build_run_summary(self, record: dict[str, Any]) -> RunSummary:
        results = [
            AgentExecution(
                agent=item.get("agent", "unknown"),
                content=item.get("content", ""),
                metadata=item.get("metadata", {}),
            )
            for item in (record["results"] or [])
        ]
        return RunSummary(
            run_id=record["id"],
            session_id=record["session_id"],
            status=record["status"],
            trigger_message=record["trigger_message"],
            created_at=record["created_at"],
            results=results,
        )

    def _extract_plan_steps(self, plan_result: AgentResult) -> List[str]:
        plan_steps = list(plan_result.metadata.get("steps", []))
        if plan_steps:
            return plan_steps

        extracted_steps: List[str] = []
        for line in plan_result.content.splitlines():
            stripped_line = line.strip()
            if not stripped_line or not stripped_line.startswith("-"):
                continue
            cleaned_step = stripped_line.lstrip("- ").strip()
            if cleaned_step:
                extracted_steps.append(cleaned_step)
        return extracted_steps

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

    def _clone_artifacts(self, artifacts: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {name: dict(meta) for name, meta in artifacts.items()}
