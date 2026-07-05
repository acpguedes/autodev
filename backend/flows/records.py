"""Persisted record types for flow runs, steps, and lifecycle events."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

RUN_STATUSES = frozenset(
    {"pending", "running", "waiting_human", "completed", "failed"}
)
STEP_STATUSES = frozenset({"running", "completed", "failed", "waiting_human"})


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class FlowRunRecord:
    """A persisted flow run.

    Attributes:
        run_id: Unique identifier of the run.
        flow_id: Fully qualified id of the flow definition.
        flow_version: Version of the flow definition executed.
        tenant_id: Tenant the run is scoped to.
        status: Current run status, one of :data:`RUN_STATUSES`.
        stop_reason: Machine-readable reason the run stopped, if it did.
        trigger: Normalized trigger that started the run.
        input: Run input payload.
        state: Durable run state (node outputs, cursor, metrics).
        output: Consolidated run output, when completed.
        parent_run_id: Id of the parent run for sub-flow runs.
        created_at: Creation timestamp (ISO-8601).
        updated_at: Last update timestamp (ISO-8601).
    """

    run_id: str
    flow_id: str
    flow_version: str
    tenant_id: str
    status: str
    stop_reason: str = ""
    trigger: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    parent_run_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_document(self) -> dict[str, Any]:
        """Render the run as a JSON-serializable API document."""
        return {
            "schemaVersion": "1",
            "runId": self.run_id,
            "flowId": self.flow_id,
            "flowVersion": self.flow_version,
            "tenantId": self.tenant_id,
            "status": self.status,
            "stopReason": self.stop_reason,
            "trigger": self.trigger,
            "input": self.input,
            "output": self.output,
            "parentRunId": self.parent_run_id,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True)
class FlowStepRecord:
    """A persisted node activation within a run.

    Attributes:
        step_id: Unique identifier of the step.
        run_id: Run the step belongs to.
        node_id: Id of the flow node activated.
        node_type: Type of the flow node activated.
        status: Step status, one of :data:`STEP_STATUSES`.
        attempt: 1-based attempt counter for this node activation.
        input: Rendered input passed to the node.
        output: Output produced by the node, when completed.
        error: Failure detail, when failed.
        started_at: Start timestamp (ISO-8601).
        completed_at: Completion timestamp (ISO-8601), empty while running.
        sequence: Monotonic position of the step within the run.
    """

    step_id: str
    run_id: str
    node_id: str
    node_type: str
    status: str
    attempt: int
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    sequence: int = 0

    def to_document(self) -> dict[str, Any]:
        """Render the step as a JSON-serializable API document."""
        return {
            "schemaVersion": "1",
            "stepId": self.step_id,
            "runId": self.run_id,
            "nodeId": self.node_id,
            "nodeType": self.node_type,
            "status": self.status,
            "attempt": self.attempt,
            "output": self.output,
            "error": self.error,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "sequence": self.sequence,
        }


@dataclass(frozen=True)
class FlowEventRecord:
    """A persisted, ordered flow lifecycle event.

    Attributes:
        event_id: Unique identifier of the event.
        run_id: Run the event belongs to.
        sequence: Monotonic position of the event within the run.
        name: Event name (``domain.entity.action``, past tense).
        payload: Event payload.
        created_at: Emission timestamp (ISO-8601).
    """

    event_id: str
    run_id: str
    sequence: int
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_document(self) -> dict[str, Any]:
        """Render the event as a JSON-serializable API document."""
        return {
            "schemaVersion": "1",
            "eventId": self.event_id,
            "runId": self.run_id,
            "sequence": self.sequence,
            "name": self.name,
            "payload": self.payload,
            "createdAt": self.created_at,
        }


def row_to_dict(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    """Convert a DB row (mapping-like or tuple) into a plain dict."""
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(zip(columns, row))

def decode_run(row: Any) -> FlowRunRecord:
    """Decode a ``flow_runs`` row into a :class:`FlowRunRecord`."""
    data = row_to_dict(
        row,
        (
            "run_id",
            "flow_id",
            "flow_version",
            "tenant_id",
            "status",
            "stop_reason",
            "trigger_json",
            "input_json",
            "state_json",
            "output_json",
            "parent_run_id",
            "created_at",
            "updated_at",
        ),
    )
    return FlowRunRecord(
        run_id=data["run_id"],
        flow_id=data["flow_id"],
        flow_version=data["flow_version"],
        tenant_id=data["tenant_id"],
        status=data["status"],
        stop_reason=data["stop_reason"] or "",
        trigger=load_json(data["trigger_json"]) or {},
        input=load_json(data["input_json"]) or {},
        state=load_json(data["state_json"]) or {},
        output=load_json(data["output_json"]),
        parent_run_id=data["parent_run_id"],
        created_at=str(data["created_at"]),
        updated_at=str(data["updated_at"]),
    )

def decode_step(row: Any) -> FlowStepRecord:
    """Decode a ``flow_steps`` row into a :class:`FlowStepRecord`."""
    data = row_to_dict(
        row,
        (
            "step_id",
            "run_id",
            "node_id",
            "node_type",
            "status",
            "attempt",
            "input_json",
            "output_json",
            "error",
            "started_at",
            "completed_at",
            "sequence",
        ),
    )
    return FlowStepRecord(
        step_id=data["step_id"],
        run_id=data["run_id"],
        node_id=data["node_id"],
        node_type=data["node_type"],
        status=data["status"],
        attempt=int(data["attempt"]),
        input=load_json(data["input_json"]) or {},
        output=load_json(data["output_json"]),
        error=data["error"] or "",
        started_at=str(data["started_at"]),
        completed_at=str(data["completed_at"] or ""),
        sequence=int(data["sequence"]),
    )

def decode_event(row: Any) -> FlowEventRecord:
    """Decode a ``flow_events`` row into a :class:`FlowEventRecord`."""
    data = row_to_dict(
        row,
        ("event_id", "run_id", "sequence", "name", "payload_json", "created_at"),
    )
    return FlowEventRecord(
        event_id=data["event_id"],
        run_id=data["run_id"],
        sequence=int(data["sequence"]),
        name=data["name"],
        payload=load_json(data["payload_json"]) or {},
        created_at=str(data["created_at"]),
    )

def load_json(value: Any) -> Any:
    """Parse a JSON column value that may already be decoded (JSONB)."""
    if value is None or isinstance(value, (dict, list)):
        return value
    text = str(value)
    if not text or text == "null":
        return None
    return json.loads(text)


__all__ = [
    "FlowEventRecord",
    "FlowRunRecord",
    "FlowStepRecord",
    "RUN_STATUSES",
    "STEP_STATUSES",
    "decode_event",
    "decode_run",
    "decode_step",
    "load_json",
    "row_to_dict",
]
