"""v2 Control Plane API — turns (E16-S1-T1).

Replaces the legacy root-relative ``POST /chat`` endpoint
(``backend/api/main.py``) with a versioned "turn" contract under ``/v2``:
posting a user message to a session creates a turn (driving the same
:meth:`~backend.orchestrator.service.OrchestratorService.handle_message`
pipeline the legacy handler already calls), and turns can be fetched
individually or listed per session with the shared ``schemaVersion``,
error-envelope, and limit/offset pagination conventions
(``backend.api.v2_common``). No new orchestration business logic is
introduced: every handler is a thin adapter over
:class:`~backend.orchestrator.service.OrchestratorService`, mirroring
``backend/api/routers/sessions_v2.py``.

A "turn" is identified 1:1 by the ``run_id`` produced by
:meth:`OrchestratorService.handle_message`, since the persistence layer's
``RunRepository`` protocol (``backend/persistence/base.py``) has no
session-agnostic ``get_run(run_id)`` lookup. ``GET /v2/turns/{turnId}``
therefore searches across the (typically small) set of known sessions'
runs for the matching ``run_id``, reusing only
:class:`OrchestratorService`'s existing public ``list_sessions``/
``list_runs`` methods rather than adding a new persistence-layer method.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.rbac_v2 import require_v2_principal
from backend.api.routers.sessions_v2 import AgentExecutionV2, HistoryItemV2, RunStepV2, get_orchestrator_v2
from backend.api.v2_common import SCHEMA_VERSION_V2, PageMetaV2, PaginationParams, paginate, v2_error
from backend.orchestrator.service import OrchestratorRun, OrchestratorService, RunSummary

router = APIRouter(prefix="/v2", dependencies=[Depends(require_v2_principal)])


class TurnCreateRequestV2(BaseModel):
    """Request body for ``POST /v2/sessions/{sessionId}/turns``."""

    message: str = Field(..., min_length=1, description="User message driving this turn.")


class TurnV2(BaseModel):
    """A single turn: one user message and the run it drove."""

    schemaVersion: str = SCHEMA_VERSION_V2
    turnId: str
    sessionId: str
    message: str
    status: str
    runType: str
    currentState: str
    createdAt: str = ""
    history: list[HistoryItemV2] = Field(default_factory=list)
    results: list[AgentExecutionV2] = Field(default_factory=list)
    steps: list[RunStepV2] = Field(default_factory=list)


class TurnListV2(BaseModel):
    """Paginated collection of :class:`TurnV2`."""

    schemaVersion: str = SCHEMA_VERSION_V2
    items: list[TurnV2]
    page: PageMetaV2


def _to_turn_v2_from_run(run: OrchestratorRun, message: str) -> TurnV2:
    """Convert a freshly produced :class:`OrchestratorRun` into a :class:`TurnV2`.

    Args:
        run: The run produced by :meth:`OrchestratorService.handle_message`.
        message: The user message that drove this turn (echoed back, since
            :class:`OrchestratorRun` itself does not carry it).

    Returns:
        The typed ``/v2`` turn response model.
    """
    return TurnV2(
        turnId=run.run_id,
        sessionId=run.session_id,
        message=message,
        status=run.status,
        runType=run.run_type,
        currentState=run.current_state,
        createdAt=datetime.now(timezone.utc).isoformat(),
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


def _to_turn_v2_from_run_summary(summary: RunSummary) -> TurnV2:
    """Convert a stored :class:`RunSummary` into a :class:`TurnV2`.

    Args:
        summary: A previously recorded run, as returned by
            :meth:`OrchestratorService.list_runs`.

    Returns:
        The typed ``/v2`` turn response model. ``history`` is left empty:
        :class:`RunSummary` does not carry the session's conversational
        history (only :class:`OrchestratorRun`, returned at creation time,
        does).
    """
    return TurnV2(
        turnId=summary.run_id,
        sessionId=summary.session_id,
        message=summary.trigger_message,
        status=summary.status,
        runType=summary.run_type,
        currentState=summary.current_state,
        createdAt=summary.created_at,
        history=[],
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


def _find_turn_by_id(orchestrator: OrchestratorService, turn_id: str) -> RunSummary | None:
    """Search every known session's runs for one matching *turn_id*.

    A turn is identified 1:1 by its underlying ``run_id``. There is no
    session-agnostic run lookup in the persistence layer (see module
    docstring), so this composes only :class:`OrchestratorService`'s
    existing public ``list_sessions``/``list_runs`` methods.

    Args:
        orchestrator: Orchestrator service dependency.
        turn_id: The turn (run) identifier to search for.

    Returns:
        The matching :class:`RunSummary`, or ``None`` if no session has a
        run with that id.
    """
    for session in orchestrator.list_sessions():
        for run in orchestrator.list_runs(session.session_id):
            if run.run_id == turn_id:
                return run
    return None


@router.post("/sessions/{session_id}/turns", response_model=TurnV2, status_code=201, tags=["chat"])
def create_turn_v2(
    session_id: str,
    request: TurnCreateRequestV2,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
) -> TurnV2:
    """Create a turn: post a user message and drive the session's agent pipeline.

    Replaces the legacy ``POST /chat`` contract
    (``backend/api/main.py::ChatRequest``); calls the same
    :meth:`OrchestratorService.handle_message` the legacy handler calls.

    Args:
        session_id: Identifier of the session this turn belongs to.
        request: The turn creation request (user message).
        orchestrator: Orchestrator service dependency.

    Returns:
        The newly created turn.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist.
    """
    try:
        run = orchestrator.handle_message(session_id, request.message)
    except KeyError as exc:
        v2_error(404, str(exc))
    return _to_turn_v2_from_run(run, request.message)


@router.get("/turns/{turn_id}", response_model=TurnV2, tags=["chat"])
def get_turn_v2(
    turn_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
) -> TurnV2:
    """Fetch a single turn by id.

    Args:
        turn_id: Identifier of the turn (its underlying ``run_id``).
        orchestrator: Orchestrator service dependency.

    Returns:
        The requested turn.

    Raises:
        HTTPException: 404 if no turn with ``turn_id`` exists.
    """
    summary = _find_turn_by_id(orchestrator, turn_id)
    if summary is None:
        v2_error(404, f"Unknown turn_id: {turn_id}")
    return _to_turn_v2_from_run_summary(summary)


@router.get("/sessions/{session_id}/turns", response_model=TurnListV2, tags=["chat"])
def list_session_turns_v2(
    session_id: str,
    pagination: PaginationParams = Depends(),
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
) -> TurnListV2:
    """List all turns for a session.

    Args:
        session_id: Identifier of the session.
        pagination: Shared limit/offset pagination window.
        orchestrator: Orchestrator service dependency.

    Returns:
        A paginated collection of turns.

    Raises:
        HTTPException: 404 if ``session_id`` does not exist.
    """
    try:
        all_runs = orchestrator.list_runs(session_id)
    except KeyError as exc:
        v2_error(404, str(exc))
    page, page_meta = paginate(all_runs, pagination)
    return TurnListV2(items=[_to_turn_v2_from_run_summary(summary) for summary in page], page=page_meta)


__all__ = [
    "TurnCreateRequestV2",
    "TurnListV2",
    "TurnV2",
    "create_turn_v2",
    "get_turn_v2",
    "list_session_turns_v2",
    "router",
]
