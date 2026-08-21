"""v2 Control Plane API — sessions, runs, and execution plans (E9-S1-T1).

Versions the existing ``/plan``, ``/sessions``, ``/sessions/{id}/runs`` and
``/sessions/{id}/execution-plan`` endpoints in ``backend/api/main.py`` under
``/v2`` with typed request/response models (``schemaVersion``-stamped,
E9-S1-T2), a standardized error envelope, and shared limit/offset
pagination (``backend.api.v2_common``). No new orchestration business logic
is introduced: every handler is a thin adapter over
:class:`~backend.orchestrator.service.OrchestratorService`, exactly as the
v1 endpoints already are.

Sessions, their nested runs, and their nested execution plan are kept in one
file (rather than split per sub-resource), mirroring how
``backend/api/routers/flows.py`` bundles catalog/runs/events/human-in-the-
loop for the "flows" resource.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.authorization import requires_scope
from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2, PageMetaV2, PaginationParams, v2_error
from backend.execution.modes import ExecutionMode
from backend.execution.policy import PolicyMissingError
from backend.quotas.contracts import QuotaExceededError
from backend.orchestrator.service import (
    ExecutionPlan,
    OrchestratorRun,
    OrchestratorService,
    RunSummary,
    SessionSummary,
    build_default_orchestrator,
)

router = APIRouter(prefix="/v2/sessions", dependencies=[Depends(require_v2_principal)])


def get_orchestrator_v2() -> OrchestratorService:
    """Build an :class:`OrchestratorService` bound to the current runtime config.

    Constructed fresh per request, matching the convention used by every
    other ``/v2`` router's service provider (``get_flow_engine``,
    ``get_agent_registry``, ``get_active_plugin_registry``) rather than
    ``backend.api.main``'s app-wide ``lru_cache``d singleton — routers must
    not import from ``main`` (see ``backend/api/routers/__init__.py``'s
    auto-discovery convention). Session/run state is unaffected by this
    choice: it lives in the shared durable store
    (:func:`backend.persistence.get_store`), not on the service instance.
    Delegates to :func:`~backend.orchestrator.service.build_default_orchestrator`
    (E43-S6), the same construction the background message-run job handler
    uses, so both stay in sync.

    Returns:
        A new :class:`OrchestratorService`.
    """
    return build_default_orchestrator()


class HistoryItemV2(BaseModel):
    """A single conversational turn."""

    role: str
    content: str


class AgentExecutionV2(BaseModel):
    """Result produced by an agent during orchestration."""

    agent: str
    content: str
    metadata: dict[str, Any]


class RunStepV2(BaseModel):
    """A completed step within a run."""

    step_key: str
    agent: str
    status: str
    started_at: str
    completed_at: str
    attempt: int


class ExecutionTaskV2(BaseModel):
    """Executable task derived from agent analysis artifacts."""

    task_id: str
    title: str
    description: str
    source_agent: str
    category: str
    status: str


class SessionCreateRequestV2(BaseModel):
    """Request body for ``POST /v2/sessions``."""

    goal: str = Field(..., min_length=1, description="High level goal for the new session.")


class SessionV2(BaseModel):
    """A session, as returned by create/list/get.

    ``history`` is populated by ``GET /v2/sessions/{id}``. It is empty in
    ``GET /v2/sessions`` listings, which report ``message_count`` and
    ``last_activity`` instead of replaying every session's conversation
    (E44-S3) — fetch the session itself to read its history.
    """

    schemaVersion: str = SCHEMA_VERSION_V2
    session_id: str
    goal: str
    plan: list[str]
    status: str
    history: list[HistoryItemV2] = Field(default_factory=list)
    message_count: int = 0
    last_activity: str | None = None


class SessionListV2(BaseModel):
    """Paginated collection of :class:`SessionV2`."""

    schemaVersion: str = SCHEMA_VERSION_V2
    items: list[SessionV2]
    page: PageMetaV2


class RunV2(BaseModel):
    """A single historical run, as returned by ``GET .../runs``."""

    schemaVersion: str = SCHEMA_VERSION_V2
    run_id: str
    session_id: str
    status: str
    run_type: str
    current_state: str
    trigger_message: str
    created_at: str
    results: list[AgentExecutionV2]
    steps: list[RunStepV2]


class RunListV2(BaseModel):
    """Paginated collection of :class:`RunV2`."""

    schemaVersion: str = SCHEMA_VERSION_V2
    items: list[RunV2]
    page: PageMetaV2


class ExecutedRunV2(BaseModel):
    """The run produced by executing a session's derived execution plan."""

    schemaVersion: str = SCHEMA_VERSION_V2
    run_id: str
    session_id: str
    status: str
    run_type: str
    current_state: str
    history: list[HistoryItemV2]
    results: list[AgentExecutionV2]
    steps: list[RunStepV2]


class ExecutionPlanV2(BaseModel):
    """Step-by-step execution plan derived from a session's artifacts."""

    schemaVersion: str = SCHEMA_VERSION_V2
    session_id: str
    summary: str
    analysis_summary: str
    tasks: list[ExecutionTaskV2]
    status: str


def _to_session_v2(summary: SessionSummary) -> SessionV2:
    """Convert a :class:`SessionSummary` into its typed ``/v2`` response model."""
    return SessionV2(
        session_id=summary.session_id,
        goal=summary.goal,
        plan=list(summary.plan),
        status=summary.status,
        history=[HistoryItemV2(role=item.role, content=item.content) for item in summary.history],
        message_count=summary.message_count,
        last_activity=summary.last_activity,
    )


def _to_run_v2(summary: RunSummary) -> RunV2:
    """Convert a :class:`RunSummary` into its typed ``/v2`` response model."""
    return RunV2(
        run_id=summary.run_id,
        session_id=summary.session_id,
        status=summary.status,
        run_type=summary.run_type,
        current_state=summary.current_state,
        trigger_message=summary.trigger_message,
        created_at=summary.created_at,
        results=[
            AgentExecutionV2(agent=result.agent, content=result.content, metadata=dict(result.metadata))
            for result in summary.results
        ],
        steps=[
            RunStepV2(
                step_key=step.step_key,
                agent=step.agent,
                status=step.status,
                started_at=step.started_at,
                completed_at=step.completed_at,
                attempt=step.attempt,
            )
            for step in summary.steps
        ],
    )


def _to_execution_plan_v2(plan: ExecutionPlan) -> ExecutionPlanV2:
    """Convert an :class:`ExecutionPlan` into its typed ``/v2`` response model."""
    return ExecutionPlanV2(
        session_id=plan.session_id,
        summary=plan.summary,
        analysis_summary=plan.analysis_summary,
        tasks=[
            ExecutionTaskV2(
                task_id=task.task_id,
                title=task.title,
                description=task.description,
                source_agent=task.source_agent,
                category=task.category,
                status=task.status,
            )
            for task in plan.tasks
        ],
        status=plan.status,
    )


def _to_executed_run_v2(run: OrchestratorRun) -> ExecutedRunV2:
    """Convert an :class:`OrchestratorRun` into its typed ``/v2`` response model."""
    return ExecutedRunV2(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        run_type=run.run_type,
        current_state=run.current_state,
        history=[HistoryItemV2(role=item.role, content=item.content) for item in run.history],
        results=[
            AgentExecutionV2(agent=result.agent, content=result.content, metadata=dict(result.metadata))
            for result in run.results
        ],
        steps=[
            RunStepV2(
                step_key=step.step_key,
                agent=step.agent,
                status=step.status,
                started_at=step.started_at,
                completed_at=step.completed_at,
                attempt=step.attempt,
            )
            for step in run.steps
        ],
    )


@requires_scope("session:write")
@router.post("", response_model=SessionV2, status_code=201, tags=["sessions"])
def create_session_v2(
    request: SessionCreateRequestV2,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> SessionV2:
    """Create a new session and generate its initial plan.

    Args:
        request: The session creation request (goal).
        orchestrator: Orchestrator service dependency.
        principal: Authenticated caller; its tenant owns the new session.

    Returns:
        The newly created session.
    """
    plan_session = orchestrator.create_plan(request.goal, tenant_id=principal.tenant_id)
    return SessionV2(
        session_id=plan_session.session_id,
        goal=plan_session.goal,
        plan=list(plan_session.plan),
        status=plan_session.status,
        history=[],
    )


@requires_scope("session:read")
@router.get("", response_model=SessionListV2, tags=["sessions"])
def list_sessions_v2(
    pagination: PaginationParams = Depends(),
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> SessionListV2:
    """List all known sessions belonging to the caller's tenant.

    Args:
        pagination: Shared limit/offset pagination window.
        orchestrator: Orchestrator service dependency.
        principal: Authenticated caller; scopes the listing to its tenant.

    Returns:
        A paginated collection of sessions. Each item's ``history`` is empty
        by design (E44-S3): listings report ``message_count`` and
        ``last_activity``; ``GET /v2/sessions/{id}`` returns the
        conversation itself.
    """
    page, total = orchestrator.list_sessions_page(
        limit=pagination.limit, offset=pagination.offset, tenant_id=principal.tenant_id
    )
    page_meta = PageMetaV2(limit=pagination.limit, offset=pagination.offset, total=total)
    return SessionListV2(items=[_to_session_v2(summary) for summary in page], page=page_meta)


@requires_scope("session:read")
@router.get("/{session_id}", response_model=SessionV2, tags=["sessions"])
def get_session_v2(
    session_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> SessionV2:
    """Fetch a single session by id, scoped to the caller's tenant.

    Args:
        session_id: Identifier of the session.
        orchestrator: Orchestrator service dependency.
        principal: Authenticated caller; a session owned by another tenant
            is treated exactly like a nonexistent one.

    Returns:
        The requested session.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist for the caller's
            tenant.
    """
    try:
        summary = orchestrator.get_session(session_id, tenant_id=principal.tenant_id)
    except KeyError as exc:
        v2_error(404, str(exc))
    return _to_session_v2(summary)


@requires_scope("run:read")
@router.get("/{session_id}/runs", response_model=RunListV2, tags=["runs"])
def list_session_runs_v2(
    session_id: str,
    pagination: PaginationParams = Depends(),
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> RunListV2:
    """List all historical runs for a session owned by the caller's tenant.

    Args:
        session_id: Identifier of the session.
        pagination: Shared limit/offset pagination window.
        orchestrator: Orchestrator service dependency.
        principal: Authenticated caller.

    Returns:
        A paginated collection of runs.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist for the caller's
            tenant.
    """
    try:
        page, total = orchestrator.list_runs_page(
            session_id,
            limit=pagination.limit,
            offset=pagination.offset,
            tenant_id=principal.tenant_id,
        )
    except KeyError as exc:
        v2_error(404, str(exc))
    page_meta = PageMetaV2(limit=pagination.limit, offset=pagination.offset, total=total)
    return RunListV2(items=[_to_run_v2(summary) for summary in page], page=page_meta)


@requires_scope("session:read")
@router.get("/{session_id}/execution-plan", response_model=ExecutionPlanV2, tags=["planning"])
def get_execution_plan_v2(
    session_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> ExecutionPlanV2:
    """Derive an execution plan from a session's accumulated agent artifacts.

    Args:
        session_id: Identifier of the session.
        orchestrator: Orchestrator service dependency.
        principal: Authenticated caller.

    Returns:
        The derived execution plan.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist for the caller's
            tenant.
    """
    try:
        plan = orchestrator.build_execution_plan(session_id, tenant_id=principal.tenant_id)
    except KeyError as exc:
        v2_error(404, str(exc))
    return _to_execution_plan_v2(plan)


@requires_scope("run:write")
@router.post("/{session_id}/execution-plan/execute", response_model=ExecutedRunV2, tags=["planning"])
def execute_execution_plan_v2(
    session_id: str,
    mode: ExecutionMode = ExecutionMode.AUTO,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> ExecutedRunV2:
    """Execute a session's derived execution plan and record the run.

    Args:
        session_id: Identifier of the session.
        mode: Execution mode (E14-S3) — ``auto`` (default), ``approval``,
            or ``hybrid``. A run may come back ``status: "awaiting_approval"``
            rather than ``"completed"``; resume it via
            ``POST .../execution-plan/resume`` once its pending decision
            (``GET /v2/execution/decisions``) is resolved.
        orchestrator: Orchestrator service dependency.
        principal: Authenticated caller.

    Returns:
        The run — completed, or paused awaiting a decision.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist for the caller's
            tenant; 400 if the session has no executable tasks; 403 if
            ``hybrid``/``approval`` mode needs a policy decision and
            production has no execution policy configured for this tenant
            (ADR-022); 429 if the tenant is at its concurrent-run quota
            (ADR-019).
    """
    try:
        run = orchestrator.execute_plan(session_id, tenant_id=principal.tenant_id, mode=mode)
    except KeyError as exc:
        v2_error(404, str(exc))
    except ValueError as exc:
        v2_error(400, str(exc))
    except QuotaExceededError as exc:
        v2_error(429, str(exc))
    except PolicyMissingError as exc:
        v2_error(403, str(exc))
    return _to_executed_run_v2(run)


@requires_scope("run:write")
@router.post("/{session_id}/execution-plan/resume", response_model=ExecutedRunV2, tags=["planning"])
def resume_execution_plan_v2(
    session_id: str,
    run_id: str,
    mode: ExecutionMode = ExecutionMode.AUTO,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> ExecutedRunV2:
    """Resume a plan-execution run paused awaiting a human decision (E14-S3).

    Args:
        session_id: Identifier of the session the paused run belongs to.
        run_id: The paused run to resume.
        mode: Execution mode for the resumed portion — pass the same mode
            the run started with; mode is a per-call parameter, not
            persisted run state.
        orchestrator: Orchestrator service dependency.
        principal: Authenticated caller.

    Returns:
        The run — completed, or paused again at the next task needing a decision.

    Raises:
        HTTPException: 404 if ``session_id``/``run_id`` do not exist for
            the caller's tenant; 400 if the run is not currently awaiting a
            decision; 403 per :func:`execute_execution_plan_v2`; 429 if the
            tenant is at its concurrent-run quota.
    """
    try:
        run = orchestrator.resume_plan_execution(
            session_id, run_id, tenant_id=principal.tenant_id, mode=mode
        )
    except KeyError as exc:
        v2_error(404, str(exc))
    except ValueError as exc:
        v2_error(400, str(exc))
    except QuotaExceededError as exc:
        v2_error(429, str(exc))
    except PolicyMissingError as exc:
        v2_error(403, str(exc))
    return _to_executed_run_v2(run)


__all__ = [
    "create_session_v2",
    "execute_execution_plan_v2",
    "get_execution_plan_v2",
    "get_orchestrator_v2",
    "get_session_v2",
    "list_session_runs_v2",
    "list_sessions_v2",
    "resume_execution_plan_v2",
    "router",
]
