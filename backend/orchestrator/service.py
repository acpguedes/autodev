"""Service responsible for coordinating agent executions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Fallback StrEnum compatible with Python 3.10."""

        pass


from typing import Any, Dict, Iterable, List, Mapping, TypedDict
from pathlib import Path
from uuid import uuid4

from langgraph.graph import END, StateGraph

from backend.agents import (
    AGENT_METADATA_MODELS,
    Agent,
    AgentContext,
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
from backend.events.runtime import emit_event
from backend.execution.executor import TaskExecutor
from backend.execution.runner import InProcessActionRunner
from backend.persistence import DurableStore, get_store
from backend.persistence.tenancy import DEFAULT_TENANT_ID
from backend.observability.tracing import trace_run, trace_run_step
from backend.quotas.contracts import QuotaDenialReason, QuotaExceededError, QuotaResource
from backend.quotas.service import QuotaService


@dataclass(slots=True)
class HistoryItem:
    """Represents a single conversational turn."""

    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        """Render this history item as a plain dict."""
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
    PLAN_EXECUTION = "plan_execution"


class RunStatus(StrEnum):
    """Top-level states used by the explicit workflow engine slice."""

    AWAITING_INPUT = "awaiting_input"
    RUNNING = "running"
    COMPLETED = "completed"


class StepStatus(StrEnum):
    """Execution status for an individual workflow step."""

    COMPLETED = "completed"
    FAILED = "failed"


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
        """Render this run step as a plain dict."""
        return {
            "step_key": self.step_key,
            "agent": self.agent,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempt": self.attempt,
        }


@dataclass(slots=True)
class ExecutionTask:
    """Executable task derived from agent analysis artifacts."""

    task_id: str
    title: str
    description: str
    source_agent: str
    category: str
    status: str = "pending"

    def to_dict(self) -> Dict[str, str]:
        """Render this execution task as a plain dict."""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "source_agent": self.source_agent,
            "category": self.category,
            "status": self.status,
        }


@dataclass(slots=True)
class ExecutionPlan:
    """Step-by-step execution plan built from session artifacts."""

    session_id: str
    summary: str
    analysis_summary: str
    tasks: List[ExecutionTask]
    status: str


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
        """Render this run as a plain dict for the API layer."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
            "run_type": self.run_type,
            "current_state": self.current_state,
            "history": [item.to_dict() for item in self.history],
            "results": [
                {
                    "agent": result.agent,
                    "content": result.content,
                    "metadata": dict(result.metadata),
                }
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
        """Render this plan session as a plain dict."""
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
        "responder",
    )


class AgentGraphState(TypedDict):
    """State propagated through the LangGraph workflow."""

    context: AgentContext
    results: List[AgentExecution]
    steps: List[RunStep]
    current_state: str
    run_id: str


class OrchestratorService:
    """Coordinate agent execution for a durable session."""

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        agents: Mapping[str, Agent] | None = None,
        store: DurableStore | None = None,
        project_root: Path | None = None,
        quota_service: QuotaService | None = None,
    ) -> None:
        """Initialize the service, wiring default agents and the durable store.

        Args:
            config: Orchestrator configuration; defaults to :class:`OrchestratorConfig`.
            agents: Additional or overriding agents, merged over the defaults.
            store: Durable store to use; defaults to :func:`backend.persistence.get_store`.
            project_root: Repository root passed to agents that need filesystem access.
            quota_service: Tenant quota/budget service (E11-S3, ADR-019); defaults
                to a fresh :class:`~backend.quotas.service.QuotaService`. Governs
                the per-tenant concurrent-run admission control in
                :meth:`handle_message`/:meth:`execute_plan`.
        """
        self._config = config or OrchestratorConfig()
        self._project_root = project_root
        self._agents = self._build_default_agents()
        if agents:
            self._agents.update(agents)
        self._store = store or get_store()
        self._quota_service = quota_service or QuotaService()
        self._graph = self._compile_graph()
        self._task_executor = TaskExecutor(
            InProcessActionRunner(project_root=(self._project_root or Path(".")).resolve())
        )

    def _acquire_run_lease(self, *, tenant_id: str, run_id: str) -> None:
        """Admit a new run against the tenant's concurrent-run ceiling, or fail closed.

        Args:
            tenant_id: Tenant the run belongs to.
            run_id: Identifier already generated for the run about to start.

        Raises:
            QuotaExceededError: If the tenant is already at its concurrent-run
                limit. No run record is created and no lease is held.
        """
        lease = self._quota_service.acquire_run_lease(tenant_id=tenant_id, run_id=run_id)
        if not lease.granted:
            policy = self._quota_service.resolve_policy(tenant_id)
            raise QuotaExceededError(
                resource=QuotaResource.CONCURRENT_RUNS,
                reason=QuotaDenialReason.LEASE_UNAVAILABLE,
                used=policy.max_concurrent_runs,
                limit=policy.max_concurrent_runs,
            )

    def describe_agent_contracts(self) -> Dict[str, Dict[str, Any]]:
        """Return JSON-schema contracts for machine-readable agent metadata."""

        return {
            agent_name: model.model_json_schema()  # type: ignore[attr-defined]
            for agent_name, model in AGENT_METADATA_MODELS.items()
        }

    def create_plan(self, goal: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> PlanSession:
        """Create a new session and generate its initial plan via the planner agent.

        Args:
            goal: High-level goal driving the session.
            tenant_id: Tenant the new session belongs to. Callers behind
                authentication must pass the resolved principal's tenant —
                never a client-supplied value.

        Returns:
            The newly created planning session.
        """
        planner: PlannerAgent = self._require_agent("planner")  # type: ignore[assignment]
        session_id = str(uuid4())
        context = AgentContext(session_id=session_id, goal=goal, user_request=goal)
        plan_result = planner.run(context)
        plan_steps = self._extract_plan_steps(plan_result)
        status = RunStatus.AWAITING_INPUT

        self._store.create_session(
            session_id=session_id,
            goal=goal,
            plan=plan_steps,
            artifacts={planner.name: dict(plan_result.metadata)},
            tenant_id=tenant_id,
        )

        return PlanSession(
            session_id=session_id, goal=goal, plan=plan_steps, status=status
        )

    def handle_message(
        self, session_id: str, message: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> OrchestratorRun:
        """Run the agent graph for a new message in an existing session.

        Args:
            session_id: Identifier of the session to continue.
            message: User message to process.
            tenant_id: Tenant the session must belong to. Callers behind
                authentication must pass the resolved principal's tenant —
                never a client-supplied value. A session belonging to a
                different tenant is treated exactly like an unknown one.

        Returns:
            The completed orchestration run.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")

        run_type = self._infer_run_type(goal=session_record["goal"], message=message)
        run_id = str(uuid4())
        self._acquire_run_lease(tenant_id=tenant_id, run_id=run_id)
        try:
            self._store.create_run(
                run_id=run_id,
                session_id=session_id,
                status=RunStatus.RUNNING,
                run_type=run_type,
                current_state="starting",
                trigger_message=message,
                results=[],
                steps=[],
                tenant_id=tenant_id,
            )
            flow_id = f"orchestrator.{run_type}"
            with trace_run(
                run_id=run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            ) as run_trace:
                result = self._execute_message_run(
                    session_record=session_record,
                    session_id=session_id,
                    message=message,
                    run_id=run_id,
                    run_type=run_type,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                )
                run_trace.finish(status="completed")
                return result
        finally:
            self._quota_service.release_run_lease(run_id)

    def _execute_message_run(
        self,
        *,
        session_record: dict[str, Any],
        session_id: str,
        message: str,
        run_id: str,
        run_type: RunType,
        flow_id: str,
        tenant_id: str,
    ) -> OrchestratorRun:
        """Execute and durably persist one already-created orchestration run.

        Args:
            session_record: Persisted session state used to build agent context.
            session_id: Session being continued.
            message: User message driving the run.
            run_id: Already-persisted run identifier.
            run_type: Explicit workflow category selected for the message.
            flow_id: Stable observability flow identifier.
            tenant_id: Tenant this run belongs to.

        Returns:
            The completed orchestration run after all persistence succeeds.
        """
        emit_event(
            "flow.run.started",
            tenant_id=tenant_id,
            partition_key=run_id,
            data={"flowId": flow_id, "flowVersion": "1.0.0"},
            subject={"runId": run_id, "sessionId": session_id},
        )
        history = [
            HistoryItem(role=record["role"], content=record["content"])
            for record in self._store.list_messages(session_id, tenant_id=tenant_id)
        ]
        user_entry = HistoryItem(role="user", content=message)
        context = AgentContext(
            session_id=session_id,
            goal=session_record["goal"],
            user_request=message,
            history=[item.to_dict() for item in history] + [user_entry.to_dict()],
            artifacts=dict(session_record["artifacts"] or {}),
        )
        initial_state: AgentGraphState = {
            "context": context,
            "results": [],
            "steps": [],
            "current_state": "starting",
            "run_id": run_id,
        }
        final_state = self._graph.invoke(initial_state)
        final_context = final_state["context"]
        results = list(final_state["results"])
        steps = list(final_state["steps"])
        current_state = final_state["current_state"]
        next_history = [HistoryItem(**item) for item in final_context.history]
        self._store.append_messages(
            session_id,
            run_id,
            [item.to_dict() for item in next_history],
            tenant_id=tenant_id,
        )
        self._store.update_session_artifacts(
            session_id,
            self._clone_artifacts(final_context.artifacts),
            tenant_id=tenant_id,
        )
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
            tenant_id=tenant_id,
        )
        emit_event(
            "flow.run.completed",
            tenant_id=tenant_id,
            partition_key=run_id,
            data={"status": "completed", "costUsd": 0.0, "tokens": 0},
            subject={"runId": run_id, "sessionId": session_id},
        )
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

    def get_plan(self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> PlanSession:
        """Fetch a session's plan.

        Args:
            session_id: Identifier of the session.
            tenant_id: Tenant the session must belong to.

        Returns:
            The session's plan.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        state = self._store.get_session(session_id, tenant_id=tenant_id)
        if state is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return PlanSession(
            session_id=state["id"],
            goal=state["goal"],
            plan=list(state["plan"] or []),
            status=RunStatus.AWAITING_INPUT,
        )

    def list_sessions(self, *, tenant_id: str = DEFAULT_TENANT_ID) -> List[SessionSummary]:
        """List all known sessions for ``tenant_id``."""
        return [
            self._build_session_summary(record, tenant_id=tenant_id)
            for record in self._store.list_sessions(tenant_id=tenant_id)
        ]

    def get_session(
        self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> SessionSummary:
        """Fetch a single session by id, scoped to ``tenant_id``.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        record = self._store.get_session(session_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return self._build_session_summary(record, tenant_id=tenant_id)

    def list_runs(
        self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> List[RunSummary]:
        """List all historical runs for a session, scoped to ``tenant_id``.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return [
            self._build_run_summary(record)
            for record in self._store.list_runs(session_id, tenant_id=tenant_id)
        ]

    def build_execution_plan(
        self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> ExecutionPlan:
        """Derive an execution plan from a session's accumulated agent artifacts.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")

        artifacts = dict(session_record.get("artifacts") or {})
        analyzer_artifact = artifacts.get("analyzer", {})
        if not analyzer_artifact:
            return ExecutionPlan(
                session_id=session_id,
                summary="Execution plan unavailable until an analysis run has completed.",
                analysis_summary="No analyzer output available yet.",
                tasks=[],
                status=RunStatus.AWAITING_INPUT,
            )

        tasks = self._build_execution_tasks(
            plan_steps=list(session_record.get("plan") or []),
            artifacts=artifacts,
        )
        return ExecutionPlan(
            session_id=session_id,
            summary="Step-by-step execution plan derived from analysis, coding, devops, and validation artifacts.",
            analysis_summary=analyzer_artifact.get("summary", ""),
            tasks=tasks,
            status=RunStatus.AWAITING_INPUT if tasks else RunStatus.COMPLETED,
        )

    def execute_plan(
        self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> OrchestratorRun:
        """Execute a session's derived execution plan and record the run.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
            ValueError: If the session has no executable tasks.
        """
        execution_plan = self.build_execution_plan(session_id, tenant_id=tenant_id)
        if not execution_plan.tasks:
            raise ValueError(
                "No executable tasks are available for the requested session."
            )

        run_id = str(uuid4())
        self._acquire_run_lease(tenant_id=tenant_id, run_id=run_id)
        try:
            return self._execute_plan_run(
                execution_plan=execution_plan,
                session_id=session_id,
                run_id=run_id,
                tenant_id=tenant_id,
            )
        finally:
            self._quota_service.release_run_lease(run_id)

    def _execute_plan_run(
        self,
        *,
        execution_plan: ExecutionPlan,
        session_id: str,
        run_id: str,
        tenant_id: str,
    ) -> OrchestratorRun:
        """Execute one already-admitted derived plan and record the run.

        Args:
            execution_plan: The already-derived, non-empty execution plan.
            session_id: Session the plan belongs to.
            run_id: Already-leased run identifier.
            tenant_id: Tenant this run belongs to.

        Returns:
            The completed orchestration run.
        """
        self._store.create_run(
            run_id=run_id,
            session_id=session_id,
            status=RunStatus.RUNNING,
            run_type=RunType.PLAN_EXECUTION,
            current_state="starting",
            trigger_message="Execute derived task plan",
            results=[],
            steps=[],
            tenant_id=tenant_id,
        )

        history = [
            HistoryItem(role=record["role"], content=record["content"])
            for record in self._store.list_messages(session_id, tenant_id=tenant_id)
        ]
        execution_entry = HistoryItem(
            role="executor",
            content=f"Executing {len(execution_plan.tasks)} planned tasks derived from the latest analysis.",
        )
        results: List[AgentExecution] = []
        steps: List[RunStep] = []
        current_state = "starting"

        for index, task in enumerate(execution_plan.tasks, start=1):
            started_at = self._timestamp()
            outcome = self._task_executor.execute(task, run_id=run_id, tenant_id=tenant_id)
            completed_at = self._timestamp()
            current_state = task.task_id
            step_status = (
                StepStatus.COMPLETED if outcome.status == "completed" else StepStatus.FAILED
            )
            results.append(
                AgentExecution(
                    agent="executor",
                    content=f"[{index}/{len(execution_plan.tasks)}] {task.title}",
                    metadata={
                        "task_id": task.task_id,
                        "title": task.title,
                        "description": task.description,
                        "source_agent": task.source_agent,
                        "category": task.category,
                        "status": outcome.status,
                        "actions": [result.to_dict() for result in outcome.results],
                    },
                )
            )
            steps.append(
                RunStep(
                    step_key=task.task_id,
                    agent=task.source_agent,
                    status=step_status,
                    started_at=started_at,
                    completed_at=completed_at,
                )
            )
            history.append(
                HistoryItem(
                    role="executor",
                    content=(
                        f"{'Completed' if step_status == StepStatus.COMPLETED else 'Failed'} "
                        f"task {index}: {task.title} ({task.category})."
                    ),
                )
            )

        history.append(execution_entry)
        ordered_history = self._normalize_execution_history(history)
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
            tenant_id=tenant_id,
        )
        self._store.append_messages(
            session_id,
            run_id,
            [item.to_dict() for item in ordered_history],
            tenant_id=tenant_id,
        )

        return OrchestratorRun(
            run_id=run_id,
            session_id=session_id,
            status=RunStatus.COMPLETED,
            run_type=RunType.PLAN_EXECUTION,
            current_state=current_state,
            history=ordered_history,
            results=results,
            steps=steps,
        )

    def _build_session_summary(
        self, record: dict[str, Any], *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> SessionSummary:
        """Build a :class:`SessionSummary` from a raw store session record."""
        history = [
            HistoryItem(role=item["role"], content=item["content"])
            for item in self._store.list_messages(record["id"], tenant_id=tenant_id)
        ]
        return SessionSummary(
            session_id=record["id"],
            goal=record["goal"],
            plan=list(record["plan"] or []),
            status=RunStatus.AWAITING_INPUT,
            history=history,
        )

    def _build_run_summary(self, record: dict[str, Any]) -> RunSummary:
        """Build a :class:`RunSummary` from a raw store run record."""
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

    def _build_execution_tasks(
        self,
        *,
        plan_steps: List[str],
        artifacts: Mapping[str, Any],
    ) -> List[ExecutionTask]:
        """Derive execution tasks from the plan steps and each agent's stored artifacts."""
        tasks: List[ExecutionTask] = []

        analyzer = artifacts.get("analyzer", {})
        architect = artifacts.get("architect", {})
        coder = artifacts.get("coder", {})
        devops = artifacts.get("devops", {})
        validator = artifacts.get("validator", {})

        for index, step in enumerate(plan_steps, start=1):
            tasks.append(
                ExecutionTask(
                    task_id=f"plan-{index}",
                    title=f"Plan step {index}",
                    description=step,
                    source_agent="planner",
                    category="planning",
                )
            )

        for index, item in enumerate(analyzer.get("next_actions", []), start=1):
            tasks.append(
                ExecutionTask(
                    task_id=f"analysis-{index}",
                    title=f"Analyze and refine scope {index}",
                    description=item,
                    source_agent="analyzer",
                    category="analysis",
                )
            )

        frontend_summary = architect.get("frontend", {}).get("summary")
        if frontend_summary:
            tasks.append(
                ExecutionTask(
                    task_id="architecture-frontend",
                    title="Apply frontend architecture guidance",
                    description=frontend_summary,
                    source_agent="architect",
                    category="architecture",
                )
            )

        backend_summary = architect.get("backend", {}).get("summary")
        if backend_summary:
            tasks.append(
                ExecutionTask(
                    task_id="architecture-backend",
                    title="Apply backend architecture guidance",
                    description=backend_summary,
                    source_agent="architect",
                    category="architecture",
                )
            )

        for index, item in enumerate(coder.get("coding_tasks", []), start=1):
            component = item.get("component", "component")
            task = item.get("task", "")
            tasks.append(
                ExecutionTask(
                    task_id=f"coding-{index}",
                    title=f"Implement {component}",
                    description=task,
                    source_agent="coder",
                    category="implementation",
                )
            )

        for key, value in (devops.get("deliverables", {}) or {}).items():
            tasks.append(
                ExecutionTask(
                    task_id=f"devops-{key}",
                    title=f"Prepare {key}",
                    description=value,
                    source_agent="devops",
                    category="operations",
                )
            )

        for index, step in enumerate(validator.get("validation_steps", []), start=1):
            tasks.append(
                ExecutionTask(
                    task_id=f"validation-{index}",
                    title=f"Validation step {index}",
                    description=step,
                    source_agent="validator",
                    category="validation",
                )
            )

        return tasks

    def _extract_plan_steps(self, plan_result: AgentResult) -> List[str]:
        """Extract plan steps from planner metadata, falling back to parsing bullet lines."""
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
            return {
                "context": next_context,
                "results": next_results,
                "steps": next_steps,
                "current_state": "completed",
                "run_id": state["run_id"],
            }

        return node

    def _clone_artifacts(
        self, artifacts: Mapping[str, Mapping[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Deep-copy one level of an artifacts mapping so callers can mutate it safely."""
        return {name: dict(meta) for name, meta in artifacts.items()}

    def _infer_run_type(self, *, goal: str, message: str) -> RunType:
        """Infer the run type from keyword heuristics over the goal and message."""
        combined = f"{goal} {message}".lower()
        if any(keyword in combined for keyword in ("doc", "readme", "documentation")):
            return RunType.DOCUMENTATION_UPDATE
        if any(
            keyword in combined
            for keyword in ("infra", "deploy", "docker", "kubernetes", "terraform")
        ):
            return RunType.DEVOPS_CHANGE
        if any(
            keyword in combined
            for keyword in ("validate", "validation", "test", "lint", "typecheck")
        ):
            return RunType.VALIDATION_ONLY
        if any(
            keyword in combined
            for keyword in ("bootstrap", "greenfield", "new project", "from scratch")
        ):
            return RunType.GREENFIELD_BOOTSTRAP
        return RunType.EXISTING_REPO_CHANGE

    def _normalize_execution_history(
        self, history: List[HistoryItem]
    ) -> List[HistoryItem]:
        """Reorder history so non-executor entries precede executor progress entries."""
        if not history:
            return []

        ordered = [item for item in history if item.role != "executor"]
        ordered.extend(item for item in history if item.role == "executor")
        return ordered

    def _timestamp(self) -> str:
        """Return the current UTC timestamp, second precision, in ``Z``-suffixed ISO 8601."""
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
