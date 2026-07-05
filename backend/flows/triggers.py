"""Trigger normalization and cron scheduling for flow runs (E3-S2-T3).

A trigger is what starts a run: a direct API call, a user message, a webhook
delivery, a matching Event Bus event, or a cron schedule. This module
normalizes each into the trigger document persisted on the run, checks the
trigger against the flow's declared ``triggers``, and evaluates 5-field cron
expressions for due schedules — without a daemon: callers (the API's
``/v2/flows/cron/tick`` or the job queue) decide when to tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.flows.model import FlowManifest


class TriggerError(ValueError):
    """Raised when a trigger is invalid or not declared by the flow."""


@dataclass(frozen=True)
class NormalizedTrigger:
    """A trigger normalized for persistence on a run.

    Attributes:
        type: Trigger kind (``api``, ``message``, ``webhook``, ``cron``,
            ``event``).
        source: Origin detail — event name for event triggers, schedule for
            cron triggers.
        payload: Trigger-specific payload persisted for auditability.
    """

    type: str
    source: str | None = None
    payload: dict[str, Any] | None = None

    def to_document(self) -> dict[str, Any]:
        """Render the trigger as the JSON document stored on the run."""
        document: dict[str, Any] = {"type": self.type}
        if self.source is not None:
            document["source"] = self.source
        if self.payload:
            document["payload"] = self.payload
        return document


def normalize_trigger(
    manifest: FlowManifest,
    trigger_type: str,
    *,
    event: str | None = None,
    payload: dict[str, Any] | None = None,
) -> NormalizedTrigger:
    """Normalize and authorize a trigger against a flow's declaration.

    Direct ``api`` starts are always allowed — the Control Plane API is the
    platform's entry point. Every other trigger type must be declared in the
    manifest's ``triggers`` (fail closed); ``event`` triggers additionally
    match on the declared event name.

    Args:
        manifest: The flow definition being triggered.
        trigger_type: Trigger kind used to start the run.
        event: Event name, for ``event`` triggers.
        payload: Trigger payload persisted for auditability.

    Returns:
        The normalized trigger.

    Raises:
        TriggerError: If the trigger is not declared by the flow.
    """
    if trigger_type == "api":
        return NormalizedTrigger(type="api", payload=dict(payload or {}))
    declared = [trigger for trigger in manifest.triggers if trigger.type == trigger_type]
    if not declared:
        raise TriggerError(
            f"flow {manifest.id!r} does not declare a {trigger_type!r} trigger"
        )
    if trigger_type == "event":
        if event is None:
            raise TriggerError("event triggers require an event name")
        if all(trigger.on != event for trigger in declared):
            raise TriggerError(
                f"flow {manifest.id!r} does not subscribe to event {event!r}"
            )
        return NormalizedTrigger(type="event", source=event, payload=dict(payload or {}))
    if trigger_type == "cron":
        schedule = declared[0].schedule
        return NormalizedTrigger(type="cron", source=schedule, payload=dict(payload or {}))
    return NormalizedTrigger(type=trigger_type, payload=dict(payload or {}))


def cron_matches(schedule: str, at: datetime) -> bool:
    """Evaluate a 5-field cron expression against a timestamp.

    Supports ``*``, ``*/step``, single values, ranges (``a-b``), lists
    (``a,b,c``), and range-with-step (``a-b/step``) per field, in the order
    minute, hour, day-of-month, month, day-of-week (0-6, Sunday=0; 7 also
    accepted as Sunday).

    Args:
        schedule: The cron expression.
        at: The timestamp to test.

    Returns:
        ``True`` when the timestamp matches the schedule.

    Raises:
        TriggerError: If the expression is malformed.
    """
    fields = schedule.split()
    if len(fields) != 5:
        raise TriggerError(f"cron expression must have 5 fields: {schedule!r}")
    weekday = (at.weekday() + 1) % 7  # Python: Monday=0 -> cron: Sunday=0
    values = (at.minute, at.hour, at.day, at.month, weekday)
    bounds = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
    for text, value, (low, high) in zip(fields, values, bounds):
        if not _field_matches(text, value, low, high):
            return False
    return True


def _field_matches(text: str, value: int, low: int, high: int) -> bool:
    """Whether one cron field matches a value.

    Args:
        text: The cron field expression.
        value: The timestamp component to test.
        low: Lowest legal value for this field.
        high: Highest legal value for this field.

    Returns:
        ``True`` when the field matches.

    Raises:
        TriggerError: If the field is malformed.
    """
    for part in text.split(","):
        expression, _, step_text = part.partition("/")
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) < 1:
                raise TriggerError(f"invalid cron step in {part!r}")
            step = int(step_text)
        if expression == "*":
            start, end = low, high
        elif "-" in expression:
            start_text, _, end_text = expression.partition("-")
            if not start_text.isdigit() or not end_text.isdigit():
                raise TriggerError(f"invalid cron range in {part!r}")
            start, end = int(start_text), int(end_text)
        elif expression.isdigit():
            start = end = int(expression)
        else:
            raise TriggerError(f"invalid cron field {part!r}")
        if start == 7 and high == 6:  # cron allows 7 for Sunday
            start = end = 0
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False


def due_cron_triggers(
    manifests: list[FlowManifest], at: datetime
) -> list[tuple[FlowManifest, str]]:
    """Find flows whose cron triggers are due at a timestamp.

    Args:
        manifests: Flow definitions to inspect.
        at: The tick timestamp.

    Returns:
        ``(manifest, schedule)`` pairs for each due cron trigger.
    """
    due: list[tuple[FlowManifest, str]] = []
    for manifest in manifests:
        for trigger in manifest.triggers:
            if trigger.type == "cron" and trigger.schedule:
                if cron_matches(trigger.schedule, at):
                    due.append((manifest, trigger.schedule))
    return due


__all__ = [
    "NormalizedTrigger",
    "TriggerError",
    "cron_matches",
    "due_cron_triggers",
    "normalize_trigger",
]
