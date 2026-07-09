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

from backend.api.rbac_v2 import require_v2_principal
from backend.api.routers.plan_approval_v2_models import (
    ExecuteApprovedRequestV2,
    PlanStepV2,
    PlanV2,
    StepContentUpdateRequestV2,
    StepCreateRequestV2,
    StepDecisionRequestV2,
)
from backend.api.routers.plan_approval_v2_events import emit_mutation, emit_transition
from backend.api.v2_common import v2_error
from backend.plans.step_state import (
    PlanStepRecord,
    StepApprovalStore,
    StepState,
    rollup_plan_state,
)

router = APIRouter(prefix="/v2/plans", tags=["plan-approval"], dependencies=[Depends(require_v2_principal)])


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


def _sync_legacy_plan(session_id: str, store: StepApprovalStore) -> list[PlanStepRecord]:
    """Mirror the tracked step list back onto the legacy plan document.

    Structural add/remove operations only mutate :class:`StepApprovalStore`;
    this keeps the legacy :class:`~backend.plans.PlanDocument` (read by
    ``backend/api/routers/plans.py`` and ``sessions_v2.py``) in sync so both
    surfaces agree on step count, content, and order. Without this, a later
    call to :meth:`StepApprovalStore.ensure_steps` (seeded from the stale
    legacy list) could resurrect a removed step at a freed-up index.

    Args:
        session_id: The owning session.
        store: The step-approval store.

    Returns:
        Every tracked step for the session after the sync, ordered by index.
    """
    records = store.list_steps(session_id)
    plan_store = _legacy_plan_store()
    plan_store.upsert_plan(session_id, [record.content for record in records])
    return records


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
    emit_transition(session_id, previous_state, record, actor)
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


@router.post("/{session_id}/steps", response_model=PlanV2, status_code=201)
def add_plan_step_v2(
    session_id: str,
    body: StepCreateRequestV2,
    store: StepApprovalStore = Depends(get_step_store),
) -> PlanV2:
    """Append a new ``draft`` step to the end of a session's plan.

    Args:
        session_id: Identifier of the session.
        body: The new step's content and actor.
        store: Step-approval store dependency.

    Returns:
        The plan after the step is appended.

    Raises:
        HTTPException: 404 if no plan document exists for the session.
    """
    _seeded_records(store, session_id)
    record = store.append_step(session_id, body.content)
    _sync_legacy_plan(session_id, store)
    emit_mutation(session_id, record.step_index, "added", body.actor)
    final_records = store.list_steps(session_id)
    return _to_plan_v2(session_id, final_records)


@router.delete("/{session_id}/steps/{step_index}", response_model=PlanV2)
def remove_plan_step_v2(
    session_id: str,
    step_index: int,
    actor: str = "anonymous",
    store: StepApprovalStore = Depends(get_step_store),
) -> PlanV2:
    """Remove a step and reindex subsequent steps to stay contiguous.

    Only steps in :data:`~backend.plans.step_state.REMOVABLE_STATES`
    (``draft``/``under_review``/``rejected``) can be removed — once a step
    is approved it is part of the execution record and can only be
    rejected, not deleted.

    Args:
        session_id: Identifier of the session.
        step_index: Zero-based step position to remove.
        actor: Who (or what) triggered the removal.
        store: Step-approval store dependency.

    Returns:
        The plan after the step is removed and remaining steps reindexed.

    Raises:
        HTTPException: 404 if the plan or the step does not exist; 400 if
            the step is not in a removable state.
    """
    _seeded_records(store, session_id)
    try:
        store.delete_step(session_id, step_index)
    except KeyError as exc:
        v2_error(404, str(exc))
    except ValueError as exc:
        v2_error(400, str(exc))
    _sync_legacy_plan(session_id, store)
    emit_mutation(session_id, step_index, "removed", actor)
    final_records = store.list_steps(session_id)
    return _to_plan_v2(session_id, final_records)


__all__ = [
    "add_plan_step_v2",
    "approve_plan_step_v2",
    "execute_approved_steps_v2",
    "get_plan_step_v2",
    "get_plan_v2",
    "get_step_store",
    "reject_plan_step_v2",
    "remove_plan_step_v2",
    "router",
    "update_plan_step_v2",
]
