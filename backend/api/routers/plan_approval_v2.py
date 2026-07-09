"""v2 Control Plane API — step-level plan approval gates (E16-S2).

Versions the legacy plan reads (``GET /sessions/{id}/execution-plan`` and
``GET /plans/{sessionId}`` in ``backend/api/routers/sessions_v2.py`` and
``backend/api/routers/plans.py``) into a step-granular approval workflow:
each step of a session's persisted plan (:class:`backend.plans.PlanStore`)
now carries its own state — ``draft -> under_review -> approved | rejected
-> executing -> completed`` (:mod:`backend.plans.step_state`) — instead of
the legacy single all-or-nothing plan-level status.

Editing a step's content is only legal before it is approved; approving or
rejecting is only legal for a step under review; ``execute-approved`` only
ever runs steps already in the ``approved`` state and refuses ``rejected``
or still-pending ones, closing the "approve individual steps, not the whole
plan" gap called out in the epic phase doc (E16-S2). Every transition emits
a ``plan.step.*`` event (E9-S3 bus) so a live timeline reflects approval
decisions as they happen.

This router is auto-included by ``backend.api.routers.include_all_routers()``;
no changes to ``main.py`` are required.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.rbac_v2 import require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2, v2_error
from backend.events.runtime import emit_event
from backend.persistence.tenancy import DEFAULT_TENANT_ID
from backend.plans.step_state import PlanStepRecord, StepApprovalStore, StepState, rollup_plan_state

router = APIRouter(prefix="/v2/plans", tags=["plan-approval"], dependencies=[Depends(require_v2_principal)])

_TRANSITION_EVENT: dict[StepState, str] = {
    StepState.UNDER_REVIEW: "plan.step.reviewing",
    StepState.APPROVED: "plan.step.approved",
    StepState.REJECTED: "plan.step.rejected",
    StepState.EXECUTING: "plan.step.executing",
    StepState.COMPLETED: "plan.step.completed",
}
"""Maps a step's new state to the ``plan.step.*`` event type it emits."""


def _legacy_plan_store() -> Any:
    """Build the legacy :class:`~backend.plans.PlanStore`, matching ``plans.py``.

    Returns:
        A plan store bound to ``DATABASE_URL`` (SQLite path or PostgreSQL).

    Raises:
        HTTPException: 503 if the ``backend.plans`` subsystem is unavailable.
    """
    try:
        from backend.plans import PlanStore
    except ImportError as exc:  # pragma: no cover - subsystem always present in this repo
        v2_error(503, "plans subsystem unavailable")
        raise exc  # unreachable; v2_error always raises
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        db_path: Optional[Path] = Path(db_url.removeprefix("sqlite:///")).expanduser().resolve()
    else:
        db_path = None
    return PlanStore(db_path=db_path)


def get_step_store() -> StepApprovalStore:
    """Build a :class:`StepApprovalStore` bound to the current database.

    Constructed fresh per request (file-backed, so this is cheap and
    durable across requests), matching the ``get_orchestrator_v2`` /
    ``_make_store`` convention used by sibling ``/v2`` routers.

    Returns:
        A new :class:`StepApprovalStore`.
    """
    return StepApprovalStore()


class PlanStepV2(BaseModel):
    """A single plan step and its current approval state."""

    schemaVersion: str = SCHEMA_VERSION_V2
    session_id: str
    step_index: int
    content: str
    state: str
    updated_at: str


class PlanV2(BaseModel):
    """A session's plan, rolled up from its steps' individual states."""

    schemaVersion: str = SCHEMA_VERSION_V2
    session_id: str
    status: str
    steps: list[PlanStepV2]


class StepContentUpdateRequestV2(BaseModel):
    """Request body for ``PUT /v2/plans/{session_id}/steps/{step_index}``."""

    content: str = Field(..., min_length=1, description="New content for the step.")


class StepDecisionRequestV2(BaseModel):
    """Request body for the ``approve``/``reject`` step actions."""

    actor: str = "anonymous"
    note: str = ""


class ExecuteApprovedRequestV2(BaseModel):
    """Request body for ``POST /v2/plans/{session_id}/execute-approved``.

    When ``step_indices`` is omitted, every currently-``approved`` step is
    executed. When given explicitly, every listed index must already be
    ``approved`` — attempting to execute a ``rejected`` or still-pending
    step is denied as an illegal transition (E16-S2-T2).
    """

    step_indices: Optional[list[int]] = None
    actor: str = "anonymous"


def _to_step_v2(record: PlanStepRecord) -> PlanStepV2:
    """Convert a :class:`PlanStepRecord` into its typed ``/v2`` response model.

    Args:
        record: The tracked step record.

    Returns:
        The equivalent response model.
    """
    return PlanStepV2(
        session_id=record.session_id,
        step_index=record.step_index,
        content=record.content,
        state=record.state.value,
        updated_at=record.updated_at,
    )


def _to_plan_v2(session_id: str, records: list[PlanStepRecord]) -> PlanV2:
    """Convert tracked step records into the rolled-up ``/v2`` plan response.

    Args:
        session_id: The owning session.
        records: Every tracked step for the session, ordered by index.

    Returns:
        The plan response, with a plan-level status rolled up from steps.
    """
    status = rollup_plan_state([record.state for record in records])
    return PlanV2(
        session_id=session_id,
        status=status.value,
        steps=[_to_step_v2(record) for record in records],
    )


def _seeded_records(store: StepApprovalStore, session_id: str) -> list[PlanStepRecord]:
    """Fetch the legacy plan and seed/return its tracked step records.

    Args:
        store: The step-approval store.
        session_id: The owning session.

    Returns:
        Every tracked step for the session, ordered by index.

    Raises:
        HTTPException: 404 if no plan document exists for the session.
    """
    plan_store = _legacy_plan_store()
    plan = plan_store.get_plan(session_id)
    if plan is None:
        v2_error(404, f"Plan for session {session_id!r} not found.")
    return store.ensure_steps(session_id, plan.steps)


def _emit_transition(
    session_id: str, previous_state: StepState, record: PlanStepRecord, actor: str
) -> None:
    """Emit the ``plan.step.*`` event for one state-machine transition.

    Best-effort: :func:`~backend.events.runtime.emit_event` never raises, so
    a bus failure cannot block an approval decision from taking effect.

    Args:
        session_id: The owning session.
        previous_state: The step's state before the transition.
        record: The step's record after the transition.
        actor: Who (or what) triggered the transition.
    """
    emit_event(
        _TRANSITION_EVENT[record.state],
        tenant_id=DEFAULT_TENANT_ID,
        partition_key=session_id,
        data={
            "sessionId": session_id,
            "stepIndex": record.step_index,
            "fromState": previous_state.value,
            "toState": record.state.value,
            "actor": actor,
        },
        subject={"sessionId": session_id, "stepIndex": str(record.step_index)},
    )


def _transition(
    store: StepApprovalStore, session_id: str, step_index: int, action: str, *, actor: str = "anonymous"
) -> PlanStepRecord:
    """Apply a state-machine action to a step and emit its transition event.

    Args:
        store: The step-approval store.
        session_id: The owning session.
        step_index: Zero-based step position.
        action: One of ``"review"``, ``"approve"``, ``"reject"``,
            ``"execute"``, ``"complete"``.
        actor: Who (or what) triggered the transition.

    Returns:
        The step's record after the transition.

    Raises:
        HTTPException: 404 if the step is unknown; 400 if ``action`` is not
            legal from the step's current state.
    """
    try:
        previous_state, record = store.transition(session_id, step_index, action)
    except KeyError as exc:
        v2_error(404, str(exc))
    except ValueError as exc:
        v2_error(400, str(exc))
    _emit_transition(session_id, previous_state, record, actor)
    return record


def _ensure_under_review(store: StepApprovalStore, session_id: str, record: PlanStepRecord) -> PlanStepRecord:
    """Auto-promote a freshly-seeded ``draft`` step to ``under_review``.

    There is no dedicated "submit for review" endpoint in this story's
    scope; a step becomes reviewable as soon as it is read or acted upon.

    Args:
        store: The step-approval store.
        session_id: The owning session.
        record: The step's current record.

    Returns:
        The step's record, promoted to ``under_review`` if it was ``draft``.
    """
    if record.state is StepState.DRAFT:
        return _transition(store, session_id, record.step_index, "review", actor="system")
    return record


@router.get("/{session_id}", response_model=PlanV2)
def get_plan_v2(session_id: str, store: StepApprovalStore = Depends(get_step_store)) -> PlanV2:
    """List a session's plan steps with each step's current approval state.

    Args:
        session_id: Identifier of the session.
        store: Step-approval store dependency.

    Returns:
        The plan, with a rolled-up plan-level status.

    Raises:
        HTTPException: 404 if no plan document exists for the session.
    """
    records = _seeded_records(store, session_id)
    records = [_ensure_under_review(store, session_id, record) for record in records]
    return _to_plan_v2(session_id, records)


@router.get("/{session_id}/steps/{step_index}", response_model=PlanStepV2)
def get_plan_step_v2(
    session_id: str, step_index: int, store: StepApprovalStore = Depends(get_step_store)
) -> PlanStepV2:
    """Read a single plan step's content and current approval state.

    Args:
        session_id: Identifier of the session.
        step_index: Zero-based step position.
        store: Step-approval store dependency.

    Returns:
        The requested step.

    Raises:
        HTTPException: 404 if the plan or the step does not exist.
    """
    _seeded_records(store, session_id)
    record = store.get_step(session_id, step_index)
    if record is None:
        v2_error(404, f"Step {step_index} not found for session {session_id!r}.")
    record = _ensure_under_review(store, session_id, record)
    return _to_step_v2(record)


@router.put("/{session_id}/steps/{step_index}", response_model=PlanStepV2)
def update_plan_step_v2(
    session_id: str,
    step_index: int,
    body: StepContentUpdateRequestV2,
    store: StepApprovalStore = Depends(get_step_store),
) -> PlanStepV2:
    """Edit a step's content prior to its approval decision.

    Args:
        session_id: Identifier of the session.
        step_index: Zero-based step position.
        body: The new step content.
        store: Step-approval store dependency.

    Returns:
        The updated step.

    Raises:
        HTTPException: 404 if the plan or the step does not exist; 400 if
            the step is no longer editable (already approved/rejected/
            executing/completed).
    """
    _seeded_records(store, session_id)
    record = store.get_step(session_id, step_index)
    if record is None:
        v2_error(404, f"Step {step_index} not found for session {session_id!r}.")
    # Editing content is itself "acting upon" the step, so a fresh ``draft``
    # step is auto-promoted to ``under_review`` on its first edit — the same
    # rule already applied to reads and approve/reject decisions.
    _ensure_under_review(store, session_id, record)
    try:
        record = store.update_content(session_id, step_index, body.content)
    except KeyError as exc:
        v2_error(404, str(exc))
    except ValueError as exc:
        v2_error(400, str(exc))
    return _to_step_v2(record)


@router.post("/{session_id}/steps/{step_index}/approve", response_model=PlanStepV2)
def approve_plan_step_v2(
    session_id: str,
    step_index: int,
    body: StepDecisionRequestV2 = StepDecisionRequestV2(),
    store: StepApprovalStore = Depends(get_step_store),
) -> PlanStepV2:
    """Approve a single plan step.

    Args:
        session_id: Identifier of the session.
        step_index: Zero-based step position.
        body: The approval decision (actor/note).
        store: Step-approval store dependency.

    Returns:
        The approved step.

    Raises:
        HTTPException: 404 if the plan or the step does not exist; 400 if
            the step is not under review (e.g. already approved/rejected).
    """
    _seeded_records(store, session_id)
    record = store.get_step(session_id, step_index)
    if record is None:
        v2_error(404, f"Step {step_index} not found for session {session_id!r}.")
    record = _ensure_under_review(store, session_id, record)
    record = _transition(store, session_id, step_index, "approve", actor=body.actor)
    return _to_step_v2(record)


@router.post("/{session_id}/steps/{step_index}/reject", response_model=PlanStepV2)
def reject_plan_step_v2(
    session_id: str,
    step_index: int,
    body: StepDecisionRequestV2 = StepDecisionRequestV2(),
    store: StepApprovalStore = Depends(get_step_store),
) -> PlanStepV2:
    """Reject a single plan step.

    Args:
        session_id: Identifier of the session.
        step_index: Zero-based step position.
        body: The rejection decision (actor/note).
        store: Step-approval store dependency.

    Returns:
        The rejected step.

    Raises:
        HTTPException: 404 if the plan or the step does not exist; 400 if
            the step is not under review (e.g. already approved/rejected).
    """
    _seeded_records(store, session_id)
    record = store.get_step(session_id, step_index)
    if record is None:
        v2_error(404, f"Step {step_index} not found for session {session_id!r}.")
    record = _ensure_under_review(store, session_id, record)
    record = _transition(store, session_id, step_index, "reject", actor=body.actor)
    return _to_step_v2(record)


@router.post("/{session_id}/execute-approved", response_model=PlanV2)
def execute_approved_steps_v2(
    session_id: str,
    body: ExecuteApprovedRequestV2 = ExecuteApprovedRequestV2(),
    store: StepApprovalStore = Depends(get_step_store),
) -> PlanV2:
    """Execute only the plan's already-``approved`` steps.

    Steps in any other state (``draft``, ``under_review``, ``rejected``,
    already ``executing``/``completed``) are never touched implicitly. When
    ``body.step_indices`` is given, every listed index must already be
    ``approved`` or the whole call is denied — this is the step-granular
    successor to the legacy all-or-nothing execute, and the illegal-
    transition guard called out in E16-S2-T2/T3.

    Args:
        session_id: Identifier of the session.
        body: Optional explicit step selection and actor.
        store: Step-approval store dependency.

    Returns:
        The plan after executing the targeted steps.

    Raises:
        HTTPException: 404 if the plan or a named step does not exist; 400
            if a named step is not ``approved``, or if no steps are
            approved and none were named explicitly.
    """
    records = _seeded_records(store, session_id)
    by_index = {record.step_index: record for record in records}

    if body.step_indices is not None:
        target_indices = body.step_indices
        for index in target_indices:
            record = by_index.get(index)
            if record is None:
                v2_error(404, f"Step {index} not found for session {session_id!r}.")
            if record.state is not StepState.APPROVED:
                v2_error(
                    400,
                    f"Cannot execute step {index} in state {record.state.value!r}; "
                    "only approved steps can be executed.",
                )
    else:
        target_indices = [record.step_index for record in records if record.state is StepState.APPROVED]
        if not target_indices:
            v2_error(400, f"No approved steps to execute for session {session_id!r}.")

    for index in target_indices:
        _transition(store, session_id, index, "execute", actor=body.actor)
        _transition(store, session_id, index, "complete", actor=body.actor)

    final_records = store.list_steps(session_id)
    return _to_plan_v2(session_id, final_records)


__all__ = [
    "approve_plan_step_v2",
    "execute_approved_steps_v2",
    "get_plan_step_v2",
    "get_plan_v2",
    "get_step_store",
    "reject_plan_step_v2",
    "router",
    "update_plan_step_v2",
]
