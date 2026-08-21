"""Service responsible for coordinating agent executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Fallback StrEnum compatible with Python 3.10."""

        pass


from typing import Any, Dict, Iterable, List, Mapping, NotRequired, Optional, Tuple, TypedDict
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
from backend.config.runtime import get_runtime_config_service
from backend.config.settings import get_settings
from backend.environments.contracts import EnvironmentBackendError, EnvironmentHandle
from backend.environments.manager import EnvironmentCapacityExceededError, EnvironmentManager
from backend.events.runtime import emit_event
from backend.execution.contracts import ExecutionAction, ExecutionActionType, ExecutionResult
from backend.execution.decisions import DecisionService
from backend.execution.executor import TaskExecutionOutcome, TaskExecutor
from backend.execution.modes import ExecutionMode
from backend.execution.policy import (
    ACTION_TYPE_TO_POLICY_CATEGORY,
    DecisionStatus,
    PendingDecision,
    PolicyEffect,
    PolicyRule,
    PolicyScopeKind,
    PolicyService,
    match_target,
)
from backend.execution.runner import InProcessActionRunner
from backend.jobs.queue import get_queue, register_handler
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
    AWAITING_APPROVAL = "awaiting_approval"
    FAILED = "failed"


class StepStatus(StrEnum):
    """Execution status for an individual workflow step."""

    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"


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
    files: List[Dict[str, str]] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Render this execution task as a plain dict."""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "source_agent": self.source_agent,
            "category": self.category,
            "status": self.status,
            "files": list(self.files),
            "commands": list(self.commands),
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
class _PreparedRun:
    """Result of :meth:`OrchestratorService._prepare_run` (E43-S6).

    Everything a new message-driven run needs before its graph is actually
    invoked: the session it belongs to, its already-persisted (and
    lease-admitted) run id, its inferred type, and its observability flow id.
    """

    session_record: Dict[str, Any]
    run_id: str
    run_type: "RunType"
    flow_id: str


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
    """Session details exposed by the API.

    Attributes:
        session_id: Identifier of the session.
        goal: The session's stated goal.
        plan: Ordered plan step descriptions.
        status: The session's current status.
        history: The conversation so far. Populated when a single session is
            fetched; intentionally empty in listings, which derive
            ``message_count``/``last_activity`` from an aggregate instead of
            replaying every session's messages (E44-S3).
        message_count: Number of messages recorded for the session.
        last_activity: Timestamp of the most recent message, or ``None`` when
            the session has none yet.
    """

    session_id: str
    goal: str
    plan: List[str]
    status: str
    history: List[HistoryItem]
    message_count: int = 0
    last_activity: Optional[str] = None


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
    """State propagated through the LangGraph workflow.

    Attributes:
        tenant_id: Tenant this run belongs to, used to emit live
            ``run.timeline.*`` events per completed agent node (E43-S6).
            Optional so the dynamic-routing graph built by
            ``backend/orchestrator/graphs.py`` (a separate node-builder,
            unaffected by this) and any other existing construction of this
            state keep working unchanged.
    """

    context: AgentContext
    results: List[AgentExecution]
    steps: List[RunStep]
    current_state: str
    run_id: str
    tenant_id: NotRequired[str]


_TIMELINE_OUTPUT_CHAR_CAP = 8000
"""Max length of one ``run.timeline.*`` event's ``output`` text (E42-S5).

Keeps a single event's payload bounded regardless of how much stdout/stderr
a task's actions captured; the tail is kept since that's what a validation
failure's relevant output usually is.
"""


def _build_timeline_output(results: Iterable[ExecutionResult]) -> str:
    """Concatenate a task's captured stdout/stderr into one log excerpt.

    Sourced from :attr:`~backend.execution.contracts.ExecutionResult.stdout`/
    ``.stderr`` -- already captured per action (E41) but never surfaced live
    before this (E42-S5): a ``run.timeline.*`` event's ``output`` field is
    exactly the "monospace stdout/log excerpt" it was designed to carry
    (``backend.events.catalog.RunTimelineStepData``).

    Args:
        results: Per-action results from one task's execution, in dispatch
            order.

    Returns:
        The concatenated excerpt, tail-truncated to
        :data:`_TIMELINE_OUTPUT_CHAR_CAP`.
    """
    parts = [text for result in results for text in (result.stdout, result.stderr) if text]
    output = "\n".join(parts)
    if len(output) > _TIMELINE_OUTPUT_CHAR_CAP:
        output = output[-_TIMELINE_OUTPUT_CHAR_CAP:]
    return output


class OrchestratorService:
    """Coordinate agent execution for a durable session."""

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        agents: Mapping[str, Agent] | None = None,
        store: DurableStore | None = None,
        project_root: Path | None = None,
        quota_service: QuotaService | None = None,
        policy_service: PolicyService | None = None,
        decision_service: DecisionService | None = None,
        environment_manager: EnvironmentManager | None = None,
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
            policy_service: Execution policy engine (E14-S2, ADR-022); defaults
                to a fresh :class:`~backend.execution.policy.PolicyService`.
                Gates every action :meth:`execute_plan` dispatches.
            decision_service: Human-decision service (E14-S3); defaults to a
                fresh :class:`~backend.execution.decisions.DecisionService`.
                Backs approval/hybrid-mode pauses in :meth:`execute_plan`/
                :meth:`resume_plan_execution`.
            environment_manager: Isolated execution-environment lifecycle
                manager (E32); defaults to a fresh
                :class:`~backend.environments.manager.EnvironmentManager`.
                :meth:`_process_tasks` provisions one environment per
                dispatch batch, scopes every derived action's runner to it,
                and tears it down (collecting artifacts) once the batch
                finishes or pauses.
        """
        self._config = config or OrchestratorConfig()
        self._project_root = project_root
        self._agents = self._build_default_agents()
        if agents:
            self._agents.update(agents)
        self._store = store or get_store()
        self._quota_service = quota_service or QuotaService()
        self._policy_service = policy_service or PolicyService()
        self._decision_service = decision_service or DecisionService()
        self._environment_manager = environment_manager or EnvironmentManager()
        self._graph = self._compile_graph()
        self._composite_runner = InProcessActionRunner(
            project_root=(self._project_root or Path(".")).resolve(),
            environment_manager=self._environment_manager,
        )
        self._task_executor = TaskExecutor(self._composite_runner, policy=self._policy_service)

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

    def _prepare_run(
        self, session_id: str, message: str, *, tenant_id: str
    ) -> "_PreparedRun":
        """Validate the session, admit the run, and persist its initial row.

        Shared setup for :meth:`handle_message` (runs the graph inline) and
        :meth:`begin_message` (E43-S6: runs the graph in a background job so
        the run_id reaches the caller before the graph does) — both need the
        exact same session lookup, run-type inference, lease acquisition, and
        initial ``RunStatus.RUNNING`` row before diverging on how the graph
        itself gets invoked.

        Args:
            session_id: Identifier of the session to continue.
            message: User message to process.
            tenant_id: Tenant the session must belong to.

        Returns:
            The prepared run's session record, run id, run type, and flow id.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
            QuotaExceededError: If the tenant is at its concurrent-run limit.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")

        run_type = self._infer_run_type(goal=session_record["goal"], message=message)
        run_id = str(uuid4())
        self._acquire_run_lease(tenant_id=tenant_id, run_id=run_id)
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
        # Emitted here (synchronously, before returning) rather than at the
        # top of _execute_message_run: this event is what creates the run's
        # EventStore projection (backend/events/store.py's append ->
        # _upsert_projection), which /v2/runs/{id}/events/stream's existence
        # check (backend/api/routers/runs_stream_v2.py) requires. Since
        # E43-S6's begin_message defers _execute_message_run to a background
        # job, leaving this emit there would race the caller opening that
        # stream immediately after begin_message returns -- a real,
        # intermittent 404, not just a test timing artifact.
        emit_event(
            "flow.run.started",
            tenant_id=tenant_id,
            partition_key=run_id,
            data={"flowId": flow_id, "flowVersion": "1.0.0"},
            subject={"runId": run_id, "sessionId": session_id},
        )
        return _PreparedRun(
            session_record=session_record,
            run_id=run_id,
            run_type=run_type,
            flow_id=flow_id,
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
        prepared = self._prepare_run(session_id, message, tenant_id=tenant_id)
        try:
            with trace_run(
                run_id=prepared.run_id,
                tenant_id=tenant_id,
                flow_id=prepared.flow_id,
            ) as run_trace:
                result = self._execute_message_run(
                    session_record=prepared.session_record,
                    session_id=session_id,
                    message=message,
                    run_id=prepared.run_id,
                    run_type=prepared.run_type,
                    flow_id=prepared.flow_id,
                    tenant_id=tenant_id,
                )
                run_trace.finish(status="completed")
                return result
        finally:
            self._quota_service.release_run_lease(prepared.run_id)

    def begin_message(
        self, session_id: str, message: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> OrchestratorRun:
        """Start a new message's agent graph in the background and return immediately (E43-S6).

        Unlike :meth:`handle_message`, this returns as soon as the run is
        admitted and its row persisted -- before the (potentially
        multi-minute, multi-agent) graph runs -- so the caller has a
        ``run_id`` to open a live ``run.timeline.*``/``execution.action.*``
        event-stream subscription against while the run is still in
        progress, instead of only after it has already finished. The graph
        itself, and every event it emits mid-run, are unchanged; only when
        the caller learns the run_id changes.

        Args:
            session_id: Identifier of the session to continue.
            message: User message to process.
            tenant_id: Tenant the session must belong to.

        Returns:
            An :class:`OrchestratorRun` reflecting the just-created,
            still-``running`` state (empty ``history``/``results``/
            ``steps``) -- poll :meth:`get_run`/``GET /v2/turns/{id}`` for
            the real, completed result.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
            QuotaExceededError: If the tenant is at its concurrent-run limit.
        """
        prepared = self._prepare_run(session_id, message, tenant_id=tenant_id)
        get_queue().enqueue(
            _MESSAGE_RUN_JOB_TYPE,
            {
                "session_id": session_id,
                "message": message,
                "run_id": prepared.run_id,
                "run_type": prepared.run_type.value,
                "flow_id": prepared.flow_id,
                "tenant_id": tenant_id,
            },
        )
        return OrchestratorRun(
            run_id=prepared.run_id,
            session_id=session_id,
            status=RunStatus.RUNNING,
            run_type=prepared.run_type,
            current_state="starting",
            history=[],
            results=[],
            steps=[],
        )

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
        finalize: bool = True,
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
            finalize: Whether to persist this run's row as ``RunStatus.COMPLETED``
                and emit ``flow.run.completed`` (E43-S8). Callers that chain
                real task dispatch onto the same run_id afterward (E43-S8's
                auto-execute) pass ``False`` -- persisting ``COMPLETED`` here
                only to immediately reopen it would leave a real, if narrow,
                race window where a poller can observe a premature
                "completed" status and stop watching before the chained
                dispatch (which can take much longer) ever starts.

        Returns:
            The orchestration run reflecting this conversation's real
            results/steps -- already durably persisted as ``COMPLETED``
            when ``finalize`` is true; otherwise the caller is responsible
            for persisting the run's real final state.
        """
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
            "tenant_id": tenant_id,
        }
        final_state = self._graph.invoke(initial_state)
        final_context = final_state["context"]
        results = list(final_state["results"])
        steps = list(final_state["steps"])
        current_state = final_state["current_state"]
        next_history = [HistoryItem(**item) for item in final_context.history]
        # Only what this run added: everything up to ``len(history)`` is
        # already persisted, and the store now appends exactly what it is
        # given rather than re-reading the conversation to find the tail
        # itself (E44-S4).
        self._store.append_messages(
            session_id,
            run_id,
            [item.to_dict() for item in next_history[len(history) :]],
            tenant_id=tenant_id,
        )
        self._store.update_session_artifacts(
            session_id,
            self._clone_artifacts(final_context.artifacts),
            tenant_id=tenant_id,
        )
        if finalize:
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
        """List all known sessions for ``tenant_id``, each with its full history.

        Costs one message query per session; prefer
        :meth:`list_sessions_page` for anything that only needs a page.
        """
        return [
            self._build_session_summary(record, tenant_id=tenant_id)
            for record in self._store.list_sessions(tenant_id=tenant_id)
        ]

    def list_sessions_page(
        self, *, limit: int, offset: int, tenant_id: str = DEFAULT_TENANT_ID
    ) -> Tuple[List[SessionSummary], int]:
        """Return one page of sessions plus the tenant's total session count (E44-S3).

        Paginates in the store rather than loading every session and slicing,
        and leaves each summary's ``history`` empty — listings surface
        ``message_count``/``last_activity`` instead, so a page costs a fixed
        number of queries regardless of how many sessions or messages the
        tenant has. Fetch a single session (:meth:`get_session`) to read its
        conversation.

        Args:
            limit: Maximum number of sessions to return.
            offset: Number of sessions to skip, in listing order.
            tenant_id: Tenant to scope the listing to.

        Returns:
            A ``(page, total)`` pair.
        """
        records, total = self._store.list_sessions_page(
            limit=limit, offset=offset, tenant_id=tenant_id
        )
        page = [
            SessionSummary(
                session_id=record["id"],
                goal=record["goal"],
                plan=list(record["plan"] or []),
                status=RunStatus.AWAITING_INPUT,
                history=[],
                message_count=int(record.get("message_count", 0)),
                last_activity=record.get("last_activity"),
            )
            for record in records
        ]
        return page, total

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

    def list_runs_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> Tuple[List[RunSummary], int]:
        """Return one page of a session's runs plus its total run count (E44-S3).

        Same ordering and per-run shape as :meth:`list_runs`; the window is
        applied in SQL instead of in the API layer.

        Args:
            session_id: Identifier of the session.
            limit: Maximum number of runs to return.
            offset: Number of runs to skip, in listing order.
            tenant_id: Tenant the session must belong to.

        Returns:
            A ``(page, total)`` pair.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        records, total = self._store.list_runs_page(
            session_id, limit=limit, offset=offset, tenant_id=tenant_id
        )
        return [self._build_run_summary(record) for record in records], total

    def get_run(self, run_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> RunSummary:
        """Fetch a single run by id without knowing its session (E44-S1).

        Args:
            run_id: Identifier of the run.
            tenant_id: Tenant the run must belong to; a run owned by another
                tenant is treated exactly like a nonexistent one.

        Returns:
            The run's :class:`RunSummary`, identical in shape to the entries
            :meth:`list_runs` returns.

        Raises:
            KeyError: If ``run_id`` does not exist for ``tenant_id``.
        """
        record = self._store.get_run(run_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return self._build_run_summary(record)

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
        self,
        session_id: str,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        mode: ExecutionMode = ExecutionMode.AUTO,
    ) -> OrchestratorRun:
        """Execute a session's derived execution plan and record the run.

        Args:
            session_id: Session to derive and execute the plan for.
            tenant_id: Tenant the session must belong to.
            mode: Execution mode (E14-S3) governing whether a task's
                actions run automatically, always pause for a human
                decision, or pause only when policy doesn't cover them.
                Defaults to :attr:`~backend.execution.modes.ExecutionMode.AUTO`.

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
                mode=mode,
            )
        finally:
            self._quota_service.release_run_lease(run_id)

    def resume_plan_execution(
        self,
        session_id: str,
        run_id: str,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        mode: ExecutionMode = ExecutionMode.AUTO,
    ) -> OrchestratorRun:
        """Resume a plan-execution run paused awaiting a human decision (E14-S3).

        Re-derives the execution plan (deterministic given unchanged
        session artifacts, the same call :meth:`execute_plan` already
        makes) and continues past every task that already has a terminal
        step, picking mode-aware processing back up from the first
        non-terminal task. No task-list snapshot is persisted separately —
        the stored run's own steps are the resume checkpoint.

        Args:
            session_id: Session the paused run belongs to.
            run_id: The paused run to resume.
            tenant_id: Tenant the session/run must belong to.
            mode: Execution mode for the resumed portion of the run —
                callers are expected to pass the same mode the run started
                with; mode is a per-call parameter, not persisted run state.

        Raises:
            KeyError: If ``session_id``/``run_id`` do not exist for ``tenant_id``.
            ValueError: If the run is not currently awaiting a decision.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        run_record = self._find_run_record(session_id, run_id, tenant_id=tenant_id)
        if run_record is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        if run_record["status"] != RunStatus.AWAITING_APPROVAL:
            raise ValueError(
                f"Run {run_id!r} is not awaiting a decision (status={run_record['status']!r})."
            )

        execution_plan = self.build_execution_plan(session_id, tenant_id=tenant_id)
        existing_steps = [
            RunStep(
                step_key=item["step_key"],
                agent=item["agent"],
                status=item["status"],
                started_at=item["started_at"],
                completed_at=item["completed_at"],
                attempt=item.get("attempt", 1),
            )
            for item in (run_record["steps"] or [])
        ]
        existing_results = [
            AgentExecution(
                agent=item.get("agent", "unknown"),
                content=item.get("content", ""),
                metadata=item.get("metadata", {}),
            )
            for item in (run_record["results"] or [])
        ]
        terminal_task_ids = {
            step.step_key
            for step in existing_steps
            if step.status in (StepStatus.COMPLETED, StepStatus.FAILED)
        }
        remaining_tasks = [
            task for task in execution_plan.tasks if task.task_id not in terminal_task_ids
        ]
        # Drop the AWAITING_APPROVAL placeholder for the task we're about to
        # retry -- it is re-appended below with its real outcome.
        steps = [step for step in existing_steps if step.status != StepStatus.AWAITING_APPROVAL]
        results = [
            result for result in existing_results if result.metadata.get("status") != "awaiting_approval"
        ]
        history = [
            HistoryItem(role=record["role"], content=record["content"])
            for record in self._store.list_messages(session_id, tenant_id=tenant_id)
        ]
        persisted_count = len(history)

        self._acquire_run_lease(tenant_id=tenant_id, run_id=run_id)
        try:
            current_state, paused = self._process_tasks(
                tasks=remaining_tasks,
                run_id=run_id,
                tenant_id=tenant_id,
                mode=mode,
                results=results,
                steps=steps,
                history=history,
                total_count=len(execution_plan.tasks),
                start_index=len(execution_plan.tasks) - len(remaining_tasks) + 1,
            )
        finally:
            self._quota_service.release_run_lease(run_id)

        return self._finalize_plan_run(
            session_id=session_id,
            run_id=run_id,
            tenant_id=tenant_id,
            results=results,
            steps=steps,
            history=history,
            persisted_count=persisted_count,
            current_state=current_state,
            paused=paused,
            total_tasks=len(execution_plan.tasks),
        )

    def resolve_execution_decision(
        self,
        decision_id: str,
        *,
        tenant_id: str,
        decision: str,
        actor: str,
        persist_as_rule: bool = False,
    ) -> PendingDecision:
        """Approve or deny a pending execution-action decision (E14-S3).

        Args:
            decision_id: The decision to resolve.
            tenant_id: Caller's tenant; must match the decision's tenant.
            decision: ``"approve"`` or ``"deny"``.
            actor: Who resolved it.
            persist_as_rule: Hybrid mode's "always" option — additionally
                grants a durable dynamic permission for the decision's
                category/pattern so equivalent future actions auto-allow
                without pausing again. Ignored when ``decision == "deny"``.

        Returns:
            The resolved decision.

        Raises:
            ValueError: If ``decision`` is neither ``"approve"`` nor ``"deny"``.
            backend.execution.decisions.DecisionNotFoundError: If no such
                decision exists for ``tenant_id``.
            backend.execution.decisions.DecisionAlreadyResolvedError: If it
                was already resolved (including a concurrent timeout).
        """
        if decision not in ("approve", "deny"):
            raise ValueError(f"decision must be 'approve' or 'deny', got {decision!r}")
        status = DecisionStatus.APPROVED if decision == "approve" else DecisionStatus.DENIED
        resolved = self._decision_service.resolve(
            decision_id, tenant_id=tenant_id, decision=status, actor=actor
        )
        if persist_as_rule and status is DecisionStatus.APPROVED:
            self._policy_service.grant_dynamic_permission(
                tenant_id,
                PolicyRule(
                    category=resolved.category,
                    effect=PolicyEffect.ALLOW,
                    scope_kind=PolicyScopeKind.PROJECT,
                    scope_id="*",
                    pattern=resolved.pattern,
                ),
                actor=actor,
            )
        return resolved

    def list_pending_execution_decisions(self, *, tenant_id: str) -> List[PendingDecision]:
        """List every still-pending execution-action decision for a tenant."""
        return self._decision_service.list_pending(tenant_id)

    def _find_run_record(
        self, session_id: str, run_id: str, *, tenant_id: str
    ) -> Optional[dict[str, Any]]:
        """Find one run's raw stored record by id, or ``None`` if not found."""
        for record in self._store.list_runs(session_id, tenant_id=tenant_id):
            if record["id"] == run_id:
                return record
        return None

    def _execute_plan_run(
        self,
        *,
        execution_plan: ExecutionPlan,
        session_id: str,
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode = ExecutionMode.AUTO,
    ) -> OrchestratorRun:
        """Execute one already-admitted derived plan and record the run.

        Args:
            execution_plan: The already-derived, non-empty execution plan.
            session_id: Session the plan belongs to.
            run_id: Already-leased run identifier.
            tenant_id: Tenant this run belongs to.
            mode: Execution mode governing task-level pausing (E14-S3).

        Returns:
            The run, completed or paused awaiting a decision.
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
        persisted_count = len(history)
        results: List[AgentExecution] = []
        steps: List[RunStep] = []

        current_state, paused = self._process_tasks(
            tasks=execution_plan.tasks,
            run_id=run_id,
            tenant_id=tenant_id,
            mode=mode,
            results=results,
            steps=steps,
            history=history,
            total_count=len(execution_plan.tasks),
            start_index=1,
        )

        return self._finalize_plan_run(
            session_id=session_id,
            run_id=run_id,
            tenant_id=tenant_id,
            results=results,
            steps=steps,
            history=history,
            persisted_count=persisted_count,
            current_state=current_state,
            paused=paused,
            total_tasks=len(execution_plan.tasks),
        )

    def _process_tasks(
        self,
        *,
        tasks: List["ExecutionTask"],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
        results: List[AgentExecution],
        steps: List[RunStep],
        history: List[HistoryItem],
        total_count: int,
        start_index: int,
    ) -> tuple[str, bool]:
        """Process *tasks* in order under *mode*, appending to the given lists in place.

        Stops early (returning ``paused=True``) the moment a task requires
        a still-pending human decision — preserving every already-recorded
        step/result as partial state, strengthening E14-S1's "interrupted
        execution preserves partial state" criterion rather than adding a
        second mechanism for it.

        Provisions one E32 execution environment for this batch (a no-op
        when *tasks* is empty), scopes every dispatched action's runner to
        it, and tears it down -- collecting the batch's declared outputs
        via the artifact store first -- once the batch finishes or pauses.
        A provisioning failure (capacity ceiling or backend error) denies
        every task in the batch rather than silently falling back to
        unisolated execution (E32-S3/S4 fail-closed).

        Returns:
            ``(current_state, paused)``.
        """
        from backend.api.timeline_roles import (  # noqa: PLC0415
            timeline_event_type_for_agent_role,
        )

        current_state = steps[-1].step_key if steps else "starting"
        if not tasks:
            return current_state, False

        environment_handle: Optional[EnvironmentHandle] = None
        environment_denied_reason: Optional[str] = None
        try:
            environment_handle = self._environment_manager.provision(
                run_id=run_id,
                tenant_id=tenant_id,
                workspace_ref=str((self._project_root or Path(".")).resolve()),
            )
            self._composite_runner.bind_environment(environment_handle)
        except (EnvironmentCapacityExceededError, EnvironmentBackendError) as exc:
            environment_denied_reason = f"execution environment unavailable: {exc}"

        action_results: List[ExecutionResult] = []
        try:
            for offset, task in enumerate(tasks):
                index = start_index + offset
                started_at = self._timestamp()
                actions = self._task_executor.derive_actions(task)
                outcome, pending = self._resolve_task_actions(
                    task=task,
                    actions=actions,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    mode=mode,
                    environment_denied_reason=environment_denied_reason,
                )
                completed_at = self._timestamp()
                current_state = task.task_id

                if pending is not None:
                    results.append(
                        AgentExecution(
                            agent="executor",
                            content=f"[{index}/{total_count}] {task.title} — awaiting a decision",
                            metadata={
                                "task_id": task.task_id,
                                "title": task.title,
                                "description": task.description,
                                "source_agent": task.source_agent,
                                "category": task.category,
                                "status": "awaiting_approval",
                                "decision_id": pending.decision_id,
                                "actions": [],
                            },
                        )
                    )
                    steps.append(
                        RunStep(
                            step_key=task.task_id,
                            agent=task.source_agent,
                            status=StepStatus.AWAITING_APPROVAL,
                            started_at=started_at,
                            completed_at=completed_at,
                        )
                    )
                    history.append(
                        HistoryItem(
                            role="executor",
                            content=f"Paused task {index}: {task.title} awaiting a decision.",
                        )
                    )
                    return current_state, True

                assert outcome is not None
                self_check: Optional[str] = None
                if task.category == "validation" and task.commands:
                    outcome, self_check = self._maybe_self_repair(
                        task=task,
                        validation_outcome=outcome,
                        batch_results=action_results,
                        run_id=run_id,
                        tenant_id=tenant_id,
                        mode=mode,
                    )
                    emit_event(
                        "execution.verification.outcome",
                        tenant_id=tenant_id,
                        partition_key=run_id,
                        data={"taskId": task.task_id, "outcome": self_check},
                        subject={"runId": run_id, "taskId": task.task_id},
                    )
                action_results.extend(outcome.results)
                timeline_event_type = timeline_event_type_for_agent_role(task.source_agent)
                if timeline_event_type is not None:
                    emit_event(
                        timeline_event_type,
                        tenant_id=tenant_id,
                        partition_key=run_id,
                        data={
                            "stepKey": task.task_id,
                            "actorRole": task.source_agent,
                            "status": outcome.status,
                            "output": _build_timeline_output(outcome.results),
                        },
                        subject={"runId": run_id, "taskId": task.task_id},
                    )
                step_status = (
                    StepStatus.COMPLETED if outcome.status == "completed" else StepStatus.FAILED
                )
                execution_metadata: Dict[str, Any] = {
                    "task_id": task.task_id,
                    "title": task.title,
                    "description": task.description,
                    "source_agent": task.source_agent,
                    "category": task.category,
                    "status": outcome.status,
                    "actions": [result.to_dict() for result in outcome.results],
                }
                if self_check is not None:
                    execution_metadata["self_check"] = self_check
                results.append(
                    AgentExecution(
                        agent="executor",
                        content=f"[{index}/{total_count}] {task.title}",
                        metadata=execution_metadata,
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
            return current_state, False
        finally:
            if environment_handle is not None:
                self._environment_manager.collect_artifacts(environment_handle, action_results)
                self._environment_manager.teardown(environment_handle)
                self._composite_runner.bind_environment(None)

    def _resolve_task_actions(
        self,
        *,
        task: "ExecutionTask",
        actions: List[ExecutionAction],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
        environment_denied_reason: Optional[str] = None,
    ) -> tuple[Optional[TaskExecutionOutcome], Optional[PendingDecision]]:
        """Dispatch *actions* or request a human decision, per *mode*.

        Returns exactly one of ``(outcome, None)`` or ``(None, pending)`` —
        the latter only when a decision is still :attr:`DecisionStatus.PENDING`
        (i.e. genuinely blocking, not yet resolved or self-expired).

        Args:
            environment_denied_reason: When set (E32-S3/S4), this batch's
                execution environment failed to provision; every action is
                denied without dispatching, regardless of mode.
        """
        if environment_denied_reason is not None and actions:
            return (
                self._task_executor.deny_all(
                    actions, run_id=run_id, tenant_id=tenant_id, reason=environment_denied_reason
                ),
                None,
            )
        if not actions or mode is ExecutionMode.AUTO:
            return self._task_executor.dispatch(actions, run_id=run_id, tenant_id=tenant_id), None

        needs_decision = mode is ExecutionMode.APPROVAL or (
            mode is ExecutionMode.HYBRID
            and any(
                not self._policy_service.preview(tenant_id=tenant_id, action=action).matched
                for action in actions
            )
        )
        if not needs_decision:
            return self._task_executor.dispatch(actions, run_id=run_id, tenant_id=tenant_id), None

        primary = actions[0]
        category = ACTION_TYPE_TO_POLICY_CATEGORY[primary.type]
        pending = self._decision_service.request(
            tenant_id=tenant_id,
            run_id=run_id,
            task_id=task.task_id,
            action=primary,
            category=category,
            prompt=f"Approve {primary.type.value} for task {task.title!r}?",
            pattern=match_target(primary),
        )
        if pending.status is DecisionStatus.PENDING:
            return None, pending
        if pending.status is DecisionStatus.APPROVED:
            outcome = self._task_executor.dispatch(
                actions,
                run_id=run_id,
                tenant_id=tenant_id,
                pre_approved_action_ids=frozenset(action.action_id for action in actions),
            )
            return outcome, None
        reason = (
            "human denied this action"
            if pending.status is DecisionStatus.DENIED
            else "decision timed out (deny-and-stop fallback)"
        )
        outcome = self._task_executor.deny_all(
            actions, run_id=run_id, tenant_id=tenant_id, reason=reason
        )
        return outcome, None

    def _maybe_self_repair(
        self,
        *,
        task: "ExecutionTask",
        validation_outcome: TaskExecutionOutcome,
        batch_results: List[ExecutionResult],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
    ) -> tuple[TaskExecutionOutcome, str]:
        """Attempt one bounded coder repair when *task*'s command failed (E41-S5).

        Only called for "validation" tasks whose ``commands`` came from
        agent structured output (E41-S4) — a keyword-sniffed command never
        reaches this method, so stub/unconfigured-provider runs are
        unaffected. Exactly one retry: feeds the failure's captured output
        back to the Coder agent, scoped to the files this batch already
        wrote (never a fresh full plan), and re-runs the same validation
        command once more. The repair write still goes through
        :meth:`_resolve_task_actions` (the same approval-mode gate as any
        other write); a pending decision there is treated as a failed
        repair rather than a second nested pause, since a bounded
        best-effort retry should never silently apply an unapproved write.

        Returns:
            ``(outcome, self_check)`` — ``outcome`` is what the caller
            should record for *task* (unchanged when no repair was
            attempted); ``self_check`` is one of ``"first_try_pass"``,
            ``"repaired_then_pass"``, or ``"failed_after_retry"``.
        """
        if validation_outcome.status == "completed":
            return validation_outcome, "first_try_pass"

        written_paths = sorted({path for result in batch_results for path in result.artifacts})
        if not written_paths or self._project_root is None:
            return validation_outcome, "failed_after_retry"

        root = self._project_root.resolve()
        file_contents: Dict[str, str] = {}
        for rel_path in written_paths:
            try:
                file_contents[rel_path] = (root / rel_path).read_text(encoding="utf-8")
            except OSError:
                continue
        if not file_contents:
            return validation_outcome, "failed_after_retry"

        failure_lines: list[str] = []
        for result in validation_outcome.results:
            if result.stdout:
                failure_lines.append(f"stdout:\n{result.stdout}")
            if result.stderr:
                failure_lines.append(f"stderr:\n{result.stderr}")
            if result.error:
                failure_lines.append(f"error: {result.error}")
        failure_output = "\n".join(failure_lines) or "validation command failed"
        files_section = "\n\n".join(f"# {path}\n{content}" for path, content in file_contents.items())

        repair_context = AgentContext(
            session_id=f"{run_id}-repair",
            goal=task.description,
            user_request=(
                f"The following files were written but failed validation "
                f"({', '.join(task.commands)}). Fix them so the command passes.\n\n"
                f"Failure output:\n{failure_output}\n\n"
                f"Current file contents:\n{files_section}"
            ),
        )
        repair_result = self._require_agent("coder").run(repair_context)
        candidate_files = repair_result.metadata.get("files", [])
        repaired_files = [
            entry
            for entry in candidate_files
            if isinstance(entry, Mapping) and entry.get("path") in file_contents
        ]
        if not repaired_files:
            return validation_outcome, "failed_after_retry"

        write_actions = [
            ExecutionAction(
                action_id=f"{task.task_id}-repair-write-{index}",
                type=ExecutionActionType.CREATE_FILE,
                task_id=task.task_id,
                step_key=task.task_id,
                path=entry["path"],
                content=entry["content"],
            )
            for index, entry in enumerate(repaired_files, start=1)
        ]
        write_outcome, write_pending = self._resolve_task_actions(
            task=task, actions=write_actions, run_id=run_id, tenant_id=tenant_id, mode=mode
        )
        if write_pending is not None or write_outcome is None or write_outcome.status != "completed":
            combined = list(validation_outcome.results) + list(
                write_outcome.results if write_outcome is not None else []
            )
            return TaskExecutionOutcome(status="failed", results=combined), "failed_after_retry"

        revalidate_actions = self._task_executor.derive_actions(task)
        revalidate_outcome = self._task_executor.dispatch(
            revalidate_actions, run_id=run_id, tenant_id=tenant_id
        )
        combined_results = (
            list(validation_outcome.results)
            + list(write_outcome.results)
            + list(revalidate_outcome.results)
        )
        self_check = "repaired_then_pass" if revalidate_outcome.status == "completed" else "failed_after_retry"
        return TaskExecutionOutcome(status=revalidate_outcome.status, results=combined_results), self_check

    def _finalize_plan_run(
        self,
        *,
        session_id: str,
        run_id: str,
        tenant_id: str,
        results: List[AgentExecution],
        steps: List[RunStep],
        history: List[HistoryItem],
        persisted_count: int,
        current_state: str,
        paused: bool,
        total_tasks: int,
    ) -> OrchestratorRun:
        """Persist and return the run, completed or paused awaiting a decision.

        Args:
            session_id: Session the run belongs to.
            run_id: Identifier of the run being finalized.
            tenant_id: Tenant the run belongs to.
            results: Agent results accumulated by the run.
            steps: Step records accumulated by the run.
            history: The full conversation, including entries this run added.
            persisted_count: How many of ``history``'s entries were already in
                the store when it was loaded. Everything beyond that is the
                tail handed to :meth:`append_messages` (E44-S4).
            current_state: The run's final flow state.
            paused: Whether the run stopped awaiting a human decision.
            total_tasks: Number of planned tasks in the execution plan.

        Returns:
            The persisted run.
        """
        status = RunStatus.AWAITING_APPROVAL if paused else RunStatus.COMPLETED
        summary = (
            f"Paused after {len(steps)}/{total_tasks} planned tasks, awaiting a decision."
            if paused
            else f"Executing {total_tasks} planned tasks derived from the latest analysis."
        )
        history.append(HistoryItem(role="executor", content=summary))
        ordered_history = self._normalize_execution_history(history)
        self._store.update_run(
            run_id=run_id,
            status=status,
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
            [item.to_dict() for item in ordered_history[persisted_count:]],
            tenant_id=tenant_id,
        )

        return OrchestratorRun(
            run_id=run_id,
            session_id=session_id,
            status=status,
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
        messages = self._store.list_messages(record["id"], tenant_id=tenant_id)
        history = [
            HistoryItem(role=item["role"], content=item["content"]) for item in messages
        ]
        last_activity = str(messages[-1]["created_at"]) if messages else None
        return SessionSummary(
            session_id=record["id"],
            goal=record["goal"],
            plan=list(record["plan"] or []),
            status=RunStatus.AWAITING_INPUT,
            history=history,
            message_count=len(history),
            last_activity=last_activity,
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

        for index, item in enumerate(coder.get("files", []), start=1):
            path = item.get("path", "")
            content = item.get("content", "")
            tasks.append(
                ExecutionTask(
                    task_id=f"coding-file-{index}",
                    title=f"Write {path}",
                    description=f"Write real file content to {path}",
                    source_agent="coder",
                    category="implementation",
                    files=[{"path": path, "content": content}],
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

        for index, command in enumerate(devops.get("commands", []), start=1):
            tasks.append(
                ExecutionTask(
                    task_id=f"devops-command-{index}",
                    title=f"Run {command}",
                    description=f"Run agent-declared command: {command}",
                    source_agent="devops",
                    category="operations",
                    commands=[command],
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

        for index, command in enumerate(validator.get("commands", []), start=1):
            tasks.append(
                ExecutionTask(
                    task_id=f"validation-command-{index}",
                    title=f"Run {command}",
                    description=f"Run agent-declared command: {command}",
                    source_agent="validator",
                    category="validation",
                    commands=[command],
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

        Reuses the exact mapping/event-type/schema :meth:`_process_tasks`
        already emits for the "Run plan" pipeline
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
        emit_event(
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


def build_default_orchestrator() -> "OrchestratorService":
    """Build an :class:`OrchestratorService` bound to the current runtime config.

    The one construction every ``/v2`` request-scoped caller and the E43-S6
    background job handler below both need -- a fresh instance (matching the
    "constructed fresh per request/job, state lives in the shared durable
    store" convention already used throughout ``/v2`` routers) pointed at
    whatever project root the runtime config currently resolves to.

    Returns:
        A new :class:`OrchestratorService`.
    """
    config_service = get_runtime_config_service()
    runtime_config = config_service.apply_to_environment()
    return OrchestratorService(
        config=OrchestratorConfig(), project_root=Path(runtime_config.repository.project_root)
    )


_MESSAGE_RUN_JOB_TYPE = "orchestrator.message_run"
"""Job type for :meth:`OrchestratorService.begin_message`'s background graph run (E43-S6)."""


@register_handler(_MESSAGE_RUN_JOB_TYPE)
def _run_message_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run one message's agent graph in the background and persist its outcome.

    Registered in the same module as :meth:`OrchestratorService.begin_message`,
    which is the only thing that enqueues this job type -- guarantees this
    handler is registered before anything can try to enqueue it, the same
    pattern :mod:`backend.repository.indexing` already uses for its own job
    type.

    On success, persists the same ``RunStatus.COMPLETED`` row
    :meth:`OrchestratorService._execute_message_run` always has -- unless
    ``Settings().autodev_chat_auto_execute`` is on and the conversation
    derived at least one executable task (E43-S8), in which case this
    continues, on the *same* run_id/run row, straight into the same
    task-dispatch path "Run plan" uses (:meth:`_process_tasks` +
    :meth:`_finalize_plan_run`) before persisting the real final status --
    so real command/file-write output keeps streaming on the same live
    subscription the conversation was already using, with no second click
    and no new run_id for the frontend to hand off to. On any exception,
    persists ``RunStatus.FAILED`` with the error recorded as a synthetic
    result entry instead of leaving the row stuck at ``running`` forever
    (the failure mode :meth:`OrchestratorService.handle_message` has always
    had, silent because it previously always had an HTTP caller to surface
    a 500 to instead).

    Args:
        payload: ``session_id``, ``message``, ``run_id``, ``run_type``
            (a :class:`RunType` value string), ``flow_id``, ``tenant_id`` --
            exactly what :meth:`OrchestratorService.begin_message` enqueues.

    Returns:
        ``{"run_id": ...}``, for the job queue's own status record; the
        durably persisted run row is the result callers actually care about.
    """
    orchestrator = build_default_orchestrator()
    run_id = payload["run_id"]
    tenant_id = payload["tenant_id"]
    session_id = payload["session_id"]
    flow_id = payload["flow_id"]
    try:
        with trace_run(run_id=run_id, tenant_id=tenant_id, flow_id=flow_id) as run_trace:
            session_record = orchestrator._store.get_session(session_id, tenant_id=tenant_id)
            if session_record is None:
                raise KeyError(f"Unknown session_id: {session_id}")
            auto_execute = get_settings().autodev_chat_auto_execute
            chat_run = orchestrator._execute_message_run(
                session_record=session_record,
                session_id=session_id,
                message=payload["message"],
                run_id=run_id,
                run_type=RunType(payload["run_type"]),
                flow_id=flow_id,
                tenant_id=tenant_id,
                finalize=not auto_execute,
            )
            if auto_execute:
                execution_plan = orchestrator.build_execution_plan(session_id, tenant_id=tenant_id)
                if execution_plan.tasks:
                    results = list(chat_run.results)
                    steps = list(chat_run.steps)
                    history = [
                        HistoryItem(role=record["role"], content=record["content"])
                        for record in orchestrator._store.list_messages(session_id, tenant_id=tenant_id)
                    ]
                    persisted_count = len(history)
                    current_state, paused = orchestrator._process_tasks(
                        tasks=execution_plan.tasks,
                        run_id=run_id,
                        tenant_id=tenant_id,
                        mode=ExecutionMode.AUTO,
                        results=results,
                        steps=steps,
                        history=history,
                        total_count=len(execution_plan.tasks),
                        start_index=1,
                    )
                    orchestrator._finalize_plan_run(
                        session_id=session_id,
                        run_id=run_id,
                        tenant_id=tenant_id,
                        results=results,
                        steps=steps,
                        history=history,
                        persisted_count=persisted_count,
                        current_state=current_state,
                        paused=paused,
                        total_tasks=len(execution_plan.tasks),
                    )
                else:
                    # Auto-execute is on but this turn derived no executable
                    # tasks (e.g. a question, not a change request) --
                    # _execute_message_run was called with finalize=False and
                    # so never persisted its own completion; do it here.
                    orchestrator._store.update_run(
                        run_id=run_id,
                        status=RunStatus.COMPLETED,
                        current_state=chat_run.current_state,
                        results=[
                            {"agent": result.agent, "content": result.content, "metadata": dict(result.metadata)}
                            for result in chat_run.results
                        ],
                        steps=[step.to_dict() for step in chat_run.steps],
                        tenant_id=tenant_id,
                    )
                    emit_event(
                        "flow.run.completed",
                        tenant_id=tenant_id,
                        partition_key=run_id,
                        data={"status": "completed", "costUsd": 0.0, "tokens": 0},
                        subject={"runId": run_id, "sessionId": session_id},
                    )
            run_trace.finish(status="completed")
    except Exception as exc:  # noqa: BLE001 - any agent/graph failure must still resolve the run
        orchestrator._store.update_run(
            run_id=run_id,
            status=RunStatus.FAILED,
            current_state="failed",
            results=[{"agent": "system", "content": str(exc), "metadata": {"error": True}}],
            steps=[],
            tenant_id=tenant_id,
        )
    finally:
        orchestrator._quota_service.release_run_lease(run_id)
    return {"run_id": run_id}
