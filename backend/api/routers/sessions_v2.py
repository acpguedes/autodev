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

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.rbac_v2 import require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2, PageMetaV2, PaginationParams, paginate, v2_error
from backend.config.runtime import get_runtime_config_service
from backend.orchestrator.service import (
    ExecutionPlan,
    OrchestratorConfig,
    OrchestratorRun,
    OrchestratorService,
    RunSummary,
    SessionSummary,
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

    Returns:
        A new :class:`OrchestratorService`.
    """
    config_service = get_runtime_config_service()
    runtime_config = config_service.apply_to_environment()
    return OrchestratorService(config=OrchestratorConfig(), project_root=Path(runtime_config.repository.project_root))


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
    """A session, as returned by create/list/get."""

    schemaVersion: str = SCHEMA_VERSION_V2
    session_id: str
    goal: str
    plan: list[str]
    status: str
    history: list[HistoryItemV2] = Field(default_factory=list)


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


@router.post("", response_model=SessionV2, status_code=201, tags=["sessions"])
def create_session_v2(
    request: SessionCreateRequestV2,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
) -> SessionV2:
    """Create a new session and generate its initial plan.

    Args:
        request: The session creation request (goal).
        orchestrator: Orchestrator service dependency.

    Returns:
        The newly created session.
    """
    plan_session = orchestrator.create_plan(request.goal)
    return SessionV2(
        session_id=plan_session.session_id,
        goal=plan_session.goal,
        plan=list(plan_session.plan),
        status=plan_session.status,
        history=[],
    )


@router.get("", response_model=SessionListV2, tags=["sessions"])
def list_sessions_v2(
    pagination: PaginationParams = Depends(),
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
) -> SessionListV2:
    """List all known sessions.

    Args:
        pagination: Shared limit/offset pagination window.
        orchestrator: Orchestrator service dependency.

    Returns:
        A paginated collection of sessions.
    """
    all_sessions = orchestrator.list_sessions()
    page, page_meta = paginate(all_sessions, pagination)
    return SessionListV2(items=[_to_session_v2(summary) for summary in page], page=page_meta)


@router.get("/{session_id}", response_model=SessionV2, tags=["sessions"])
def get_session_v2(
    session_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
) -> SessionV2:
    """Fetch a single session by id.

    Args:
        session_id: Identifier of the session.
        orchestrator: Orchestrator service dependency.

    Returns:
        The requested session.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist.
    """
    try:
        summary = orchestrator.get_session(session_id)
    except KeyError as exc:
        v2_error(404, str(exc))
    return _to_session_v2(summary)


@router.get("/{session_id}/runs", response_model=RunListV2, tags=["runs"])
def list_session_runs_v2(
    session_id: str,
    pagination: PaginationParams = Depends(),
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
) -> RunListV2:
    """List all historical runs for a session.

    Args:
        session_id: Identifier of the session.
        pagination: Shared limit/offset pagination window.
        orchestrator: Orchestrator service dependency.

    Returns:
        A paginated collection of runs.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist.
    """
    try:
        all_runs = orchestrator.list_runs(session_id)
    except KeyError as exc:
        v2_error(404, str(exc))
    page, page_meta = paginate(all_runs, pagination)
    return RunListV2(items=[_to_run_v2(summary) for summary in page], page=page_meta)


@router.get("/{session_id}/execution-plan", response_model=ExecutionPlanV2, tags=["planning"])
def get_execution_plan_v2(
    session_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
) -> ExecutionPlanV2:
    """Derive an execution plan from a session's accumulated agent artifacts.

    Args:
        session_id: Identifier of the session.
        orchestrator: Orchestrator service dependency.

    Returns:
        The derived execution plan.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist.
    """
    try:
        plan = orchestrator.build_execution_plan(session_id)
    except KeyError as exc:
        v2_error(404, str(exc))
    return _to_execution_plan_v2(plan)


@router.post("/{session_id}/execution-plan/execute", response_model=ExecutedRunV2, tags=["planning"])
def execute_execution_plan_v2(
    session_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
) -> ExecutedRunV2:
    """Execute a session's derived execution plan and record the run.

    Args:
        session_id: Identifier of the session.
        orchestrator: Orchestrator service dependency.

    Returns:
        The completed run.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist; 400 if the
            session has no executable tasks.
    """
    try:
        run = orchestrator.execute_plan(session_id)
    except KeyError as exc:
        v2_error(404, str(exc))
    except ValueError as exc:
        v2_error(400, str(exc))
    return _to_executed_run_v2(run)


__all__ = [
    "create_session_v2",
    "execute_execution_plan_v2",
    "get_execution_plan_v2",
    "get_orchestrator_v2",
    "get_session_v2",
    "list_session_runs_v2",
    "list_sessions_v2",
    "router",
]
