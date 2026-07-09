"""``plan.step.*`` event emission helpers for the ``/v2/plans`` router (E16-S2 / E17-S2).

Split out of ``plan_approval_v2.py`` to keep that module under the
repository's 500-line-per-file limit. Pure event-emission logic — no
request handling or persistence lives here.
"""

from __future__ import annotations

from backend.events.runtime import emit_event
from backend.persistence.tenancy import DEFAULT_TENANT_ID
from backend.plans.step_state import PlanStepRecord, StepState

TRANSITION_EVENT: dict[StepState, str] = {
    StepState.UNDER_REVIEW: "plan.step.reviewing",
    StepState.APPROVED: "plan.step.approved",
    StepState.REJECTED: "plan.step.rejected",
    StepState.EXECUTING: "plan.step.executing",
    StepState.COMPLETED: "plan.step.completed",
}
"""Maps a step's new state to the ``plan.step.*`` event type it emits."""

MUTATION_EVENT: dict[str, str] = {"added": "plan.step.added", "removed": "plan.step.removed"}
"""Maps a structural step change to the ``plan.step.*`` event type it emits."""


def emit_transition(
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
        TRANSITION_EVENT[record.state],
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


def emit_mutation(session_id: str, step_index: int, kind: str, actor: str) -> None:
    """Emit the ``plan.step.added``/``plan.step.removed`` event for a structural change.

    Best-effort: :func:`~backend.events.runtime.emit_event` never raises, so
    a bus failure cannot block an add/remove from taking effect.

    Args:
        session_id: The owning session.
        step_index: Zero-based position of the affected step.
        kind: Either ``"added"`` or ``"removed"``.
        actor: Who (or what) triggered the change.
    """
    emit_event(
        MUTATION_EVENT[kind],
        tenant_id=DEFAULT_TENANT_ID,
        partition_key=session_id,
        data={"sessionId": session_id, "stepIndex": step_index, "actor": actor},
        subject={"sessionId": session_id, "stepIndex": str(step_index)},
    )


__all__ = ["MUTATION_EVENT", "TRANSITION_EVENT", "emit_mutation", "emit_transition"]
