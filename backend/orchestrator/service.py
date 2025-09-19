"""Service responsible for coordinating agent executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping
from uuid import uuid4

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
class SessionState:
    """In-memory representation of an orchestration session."""

    session_id: str
    goal: str
    plan: List[str]
    history: List[str] = field(default_factory=list)
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
    history: List[str]
    results: List[AgentExecution]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "history": list(self.history),
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


DEFAULT_AGENT_FACTORY: Dict[str, Agent] = {
    "planner": PlannerAgent(),
    "navigator": NavigatorAgent(),
    "analyzer": AnalyzerAgent(),
    "architect": ArchitectAgent(),
    "coder": CoderAgent(),
    "devops": DevOpsAgent(),
    "validator": ValidatorAgent(),
}


class OrchestratorService:
    """Coordinate agent execution for a session."""

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        agents: Mapping[str, Agent] | None = None,
    ) -> None:
        self._config = config or OrchestratorConfig()
        self._agents = dict(DEFAULT_AGENT_FACTORY)
        if agents:
            self._agents.update(agents)
        self._sessions: Dict[str, SessionState] = {}

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

        state.history.append(message)
        context = AgentContext(
            session_id=session_id,
            goal=state.goal,
            history=list(state.history),
            artifacts={name: dict(meta) for name, meta in state.artifacts.items()},
        )

        results: List[AgentExecution] = []
        for agent_name in self._config.agent_order:
            agent = self._require_agent(agent_name)
            agent_result: AgentResult = agent.run(context)
            execution = AgentExecution(
                agent=agent.name,
                content=agent_result.content,
                metadata=agent_result.metadata,
            )
            results.append(execution)
            state.artifacts[agent.name] = agent_result.metadata
            context = context.with_artifact(agent.name, agent_result.metadata)

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


__all__ = [
    "AgentExecution",
    "OrchestratorConfig",
    "OrchestratorRun",
    "OrchestratorService",
    "PlanSession",
    "SessionState",
]
