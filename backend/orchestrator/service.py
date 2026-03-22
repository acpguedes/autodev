"""Service responsible for coordinating agent executions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Dict, Iterable, List, Mapping, TypedDict
from pathlib import Path
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


class RunType(StrEnum):
    """Supported workflow types for orchestrator runs."""

    GREENFIELD_BOOTSTRAP = "greenfield_bootstrap"
    EXISTING_REPO_CHANGE = "existing_repo_change"
    DOCUMENTATION_UPDATE = "documentation_update"
    DEVOPS_CHANGE = "devops_change"
    VALIDATION_ONLY = "validation_only"


class RunStatus(StrEnum):
    """Top-level states used by the explicit workflow engine slice."""

    AWAITING_INPUT = "awaiting_input"
    RUNNING = "running"
    COMPLETED = "completed"


class StepStatus(StrEnum):
    """Execution status for an individual workflow step."""

    COMPLETED = "completed"


@dataclass(slots=True)
class RunStep:
    """Represents a completed step within a run."""

    step_key: str
    agent: str
    status: str
    started_at: str
    completed_at: str
    attempt: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_key": self.step_key,
            "agent": self.agent,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempt": self.attempt,
        }


@dataclass(slots=True)
class OrchestratorRun:
    """Aggregate response returned to the API layer."""

    run_id: str
    session_id: str
    status: str
    run_type: str
    current_state: str
    history: List[HistoryItem]
    results: List[AgentExecution]
    steps: List[RunStep]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
            "run_type": self.run_type,
            "current_state": self.current_state,
            "history": [item.to_dict() for item in self.history],
            "results": [
                {"agent": result.agent, "content": result.content, "metadata": dict(result.metadata)}
                for result in self.results
            ],
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(slots=True)
class PlanSession:
    """Data returned after generating a plan."""

    session_id: str
    goal: str
    plan: List[str]
    status: str = RunStatus.AWAITING_INPUT

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
    run_type: str
    current_state: str
    trigger_message: str
    created_at: str
    results: List[AgentExecution]
    steps: List[RunStep]


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
    steps: List[RunStep]
    current_state: str


class OrchestratorService:
    """Coordinate agent execution for a durable session."""

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        agents: Mapping[str, Agent] | None = None,
        store: DurableStore | None = None,
        project_root: Path | None = None,
    ) -> None:
        self._config = config or OrchestratorConfig()
        self._project_root = project_root
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
        status = RunStatus.AWAITING_INPUT

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

        run_type = self._infer_run_type(goal=session_record["goal"], message=message)
        run_id = str(uuid4())

        self._store.create_run(
            run_id=run_id,
            session_id=session_id,
            status=RunStatus.RUNNING,
            run_type=run_type,
            current_state="starting",
            trigger_message=message,
            results=[],
            steps=[],
        )

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

        initial_state: AgentGraphState = {
            "context": context,
            "results": [],
            "steps": [],
            "current_state": "starting",
        }
        final_state = self._graph.invoke(initial_state)
        final_context = final_state["context"]
        results = list(final_state["results"])
        steps = list(final_state["steps"])
        current_state = final_state["current_state"]

        self._store.update_run(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            current_state=current_state,
            results=[
                {
                    "agent": result.agent,
                    "content": result.content,
                    "metadata": dict(result.metadata),
                }
                for result in results
            ],
            steps=[step.to_dict() for step in steps],
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
            status=RunStatus.COMPLETED,
            run_type=run_type,
            current_state=current_state,
            history=next_history,
            results=results,
            steps=steps,
        )

    def get_plan(self, session_id: str) -> PlanSession:
        state = self._store.get_session(session_id)
        if state is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return PlanSession(
            session_id=state["id"],
            goal=state["goal"],
            plan=list(state["plan"] or []),
            status=RunStatus.AWAITING_INPUT,
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
            status=RunStatus.AWAITING_INPUT,
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
            run_type=record["run_type"],
            current_state=record["current_state"],
            trigger_message=record["trigger_message"],
            created_at=record["created_at"],
            results=results,
            steps=[
                RunStep(
                    step_key=item["step_key"],
                    agent=item["agent"],
                    status=item["status"],
                    started_at=item["started_at"],
                    completed_at=item["completed_at"],
                    attempt=item.get("attempt", 1),
                )
                for item in (record["steps"] or [])
            ],
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
            "navigator": NavigatorAgent(project_root=self._project_root),
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
            started_at = self._timestamp()
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
            return {
                "context": next_context,
                "results": next_results,
                "steps": next_steps,
                "current_state": "completed",
            }

        return node

    def _clone_artifacts(self, artifacts: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {name: dict(meta) for name, meta in artifacts.items()}

    def _infer_run_type(self, *, goal: str, message: str) -> RunType:
        combined = f"{goal} {message}".lower()
        if any(keyword in combined for keyword in ("doc", "readme", "documentation")):
            return RunType.DOCUMENTATION_UPDATE
        if any(keyword in combined for keyword in ("infra", "deploy", "docker", "kubernetes", "terraform")):
            return RunType.DEVOPS_CHANGE
        if any(keyword in combined for keyword in ("validate", "validation", "test", "lint", "typecheck")):
            return RunType.VALIDATION_ONLY
        if any(keyword in combined for keyword in ("bootstrap", "greenfield", "new project", "from scratch")):
            return RunType.GREENFIELD_BOOTSTRAP
        return RunType.EXISTING_REPO_CHANGE

    def _timestamp(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
