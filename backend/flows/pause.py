"""Pause records and error contracts for human-in-the-loop flows (E3-S4).

This module owns the durable pause bookkeeping the engine performs when a
``human`` node activates, plus the error vocabulary and pending-request
document shared with :mod:`backend.flows.human`. It deliberately imports
nothing from the engine so the engine can call :func:`pause_run` without an
import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.flows.handlers import NodeOutcome
from backend.flows.model import FlowNode
from backend.flows.records import FlowRunRecord, FlowStepRecord
from backend.flows.state import FlowRunStore


class FlowHumanError(RuntimeError):
    """Base error for human-in-the-loop operations (e.g. unknown run)."""


class FlowHumanStateError(FlowHumanError):
    """Raised when the run is not waiting for a human decision."""


class FlowHumanDecisionError(FlowHumanError):
    """Raised when a decision payload is invalid or the wait already expired."""


@dataclass(frozen=True)
class PendingHumanRequest:
    """The pending decision request of a run paused at a human node.

    Attributes:
        run_id: Id of the paused run.
        node_id: Id of the human node the run is waiting on.
        prompt: Prompt shown to the operator.
        form: JSON Schema of the expected decision payload, when declared.
        expires_at: ISO-8601 expiry of the wait, when the node has a timeout.
    """

    run_id: str
    node_id: str
    prompt: str
    form: dict[str, Any] | None = None
    expires_at: str | None = None

    def to_document(self) -> dict[str, Any]:
        """Render the pending request as a JSON-serializable API document."""
        return {
            "schemaVersion": "1",
            "runId": self.run_id,
            "nodeId": self.node_id,
            "prompt": self.prompt,
            "form": self.form,
            "expiresAt": self.expires_at,
        }


def pause_run(
    runs: FlowRunStore,
    run: FlowRunRecord,
    node: FlowNode,
    step: FlowStepRecord,
    state: dict[str, Any],
    outcome: NodeOutcome,
) -> FlowRunRecord:
    """Persist a human pause and return the ``waiting_human`` run record.

    The step is marked ``waiting_human`` (not completed), the cursor stays on
    the human node, pause metadata lands in the run state, and
    ``flow.run.paused`` is appended to the event store — so the wait is fully
    durable and a restarted engine resumes exactly here.

    Args:
        runs: The durable run/step/event store.
        run: The run being paused.
        node: The human node the run pauses at.
        step: The step activation now waiting for a decision.
        state: The mutable run state (cursor still on ``node``).
        outcome: The pausing outcome carrying the prompt/form/expiry output.

    Returns:
        The persisted ``waiting_human`` run record.
    """
    runs.complete_step(step.step_id, status="waiting_human", output=outcome.output)
    state["pause"] = {
        "nodeId": node.id,
        "stepId": step.step_id,
        "expiresAt": outcome.output.get("expiresAt"),
    }
    runs.update_run(run.run_id, status="waiting_human", state=state)
    runs.append_event(
        run_id=run.run_id,
        name="flow.run.paused",
        payload={
            "nodeId": node.id,
            "stepId": step.step_id,
            "prompt": outcome.output.get("prompt"),
            "expiresAt": outcome.output.get("expiresAt"),
        },
    )
    record = runs.get_run(run.run_id)
    assert record is not None  # noqa: S101 - just persisted above
    return record


__all__ = [
    "FlowHumanDecisionError",
    "FlowHumanError",
    "FlowHumanStateError",
    "PendingHumanRequest",
    "pause_run",
]
