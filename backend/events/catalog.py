"""Central event catalog and canonical envelope (E9-S3-T1/T3, reference §14.5).

Every asynchronous event on the platform is described here:

* :class:`EventEnvelope` — the canonical wire envelope, identical on the bus,
  on SSE, and on webhooks.
* :data:`EVENT_CATALOG` — the registry of every event type
  (``domain.entity.action``), its emitter, partition key semantics, and the
  pydantic model that validates its ``data`` payload.
* :func:`make_envelope` — the only sanctioned way to build an envelope: it
  validates the payload against the catalog before the event leaves the
  producer.
* :func:`is_compatible_evolution` — the additive-only compatibility rule
  (§14.7) used by contract tests to gate payload-schema changes within a
  MAJOR version.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Literal
import uuid

from pydantic import BaseModel

SCHEMA_VERSION_EVENTS = "2.0.0"
"""SemVer schema version stamped on every event envelope (§14.7)."""

_EVENT_NAME_RE = re.compile(r"^[a-z]+(\.[a-z]+){1,2}$")
"""Catalog naming rule: ``domain.entity.action`` in lowercase segments."""


class SessionCreatedData(BaseModel):
    """Payload of ``session.created``."""

    sessionId: str
    goal: str


class FlowRunStartedData(BaseModel):
    """Payload of ``flow.run.started``."""

    flowId: str
    flowVersion: str


class RunStepStartedData(BaseModel):
    """Payload of ``run.step.started``."""

    stepKey: str
    agent: str


class RunStepCompletedData(BaseModel):
    """Payload of ``run.step.completed``."""

    stepKey: str
    status: str
    attempt: int


class RunStepFailedData(BaseModel):
    """Payload of ``run.step.failed``."""

    stepKey: str
    error: str
    attempt: int


class AgentTokenDeltaData(BaseModel):
    """Payload of ``agent.token.delta`` (streaming only)."""

    stepKey: str
    delta: str


class RunHumanRequestedData(BaseModel):
    """Payload of ``run.human.requested``."""

    stepKey: str
    prompt: str


class RunHumanResolvedData(BaseModel):
    """Payload of ``run.human.resolved``."""

    stepKey: str
    decision: str


class FlowRunCompletedData(BaseModel):
    """Payload of ``flow.run.completed``."""

    status: str
    costUsd: float
    tokens: int


class FlowRunFailedData(BaseModel):
    """Payload of ``flow.run.failed``."""

    error: str
    failedStep: str


class RunBudgetExceededData(BaseModel):
    """Payload of ``run.budget.exceeded``."""

    dimension: str
    limit: float
    used: float


class GuardrailViolationBlockedData(BaseModel):
    """Payload of ``guardrail.violation.blocked``."""

    guardrailId: str
    reason: str


class PatchAppliedData(BaseModel):
    """Payload of ``patch.applied``."""

    files: list[str]
    additions: int
    deletions: int


class ValidationGateData(BaseModel):
    """Shared payload of ``validation.gate.passed`` / ``validation.gate.failed``."""

    gate: str
    report: dict[str, Any]


class EvalRunCompletedData(BaseModel):
    """Payload of ``eval.run.completed``."""

    evalId: str
    score: float
    metrics: dict[str, float]


class PluginLifecycleData(BaseModel):
    """Shared payload of ``plugin.installed`` / ``plugin.removed``."""

    pluginId: str
    version: str


class RegistryEntryData(BaseModel):
    """Shared payload of ``agent.registered`` / ``skill.registered``."""

    id: str
    version: str


class RunTimelineStepData(BaseModel):
    """Shared payload of the ``run.timeline.*`` live timeline events (E16-S1-T2).

    Each ``run.timeline.*`` type (``planning``, ``analysis``, ``patch``,
    ``validation``) represents one step of the redesigned UI's live timeline
    for a turn. Every event carries the actor role that produced it
    (E16-S1-T3, see :mod:`backend.api.timeline_roles`) and a monospace
    stdout/log excerpt so the UI can render terminal-style output per step.
    """

    stepKey: str
    actorRole: str
    status: str
    output: str
class PlanStepTransitionData(BaseModel):
    """Shared payload of ``plan.step.*`` step-approval transition events (E16-S2).

    One shared model covers every step in the ``draft -> under_review ->
    approved | rejected -> executing -> completed`` state machine (§14.5);
    ``fromState``/``toState`` disambiguate which edge fired.
    """

    sessionId: str
    stepIndex: int
    fromState: str
    toState: str
    actor: str


@dataclass(frozen=True)
class EventDefinition:
    """Catalog entry describing one event type (§14.5 table).

    Attributes:
        name: Event type in ``domain.entity.action`` form.
        emitted_by: Subsystem that produces the event.
        partition: Which envelope field the partition key is derived from;
            ordering is guaranteed only within a partition.
        data_model: Pydantic model validating the envelope ``data`` payload.
        schema_version: SemVer of the payload schema (§14.7).
    """

    name: str
    emitted_by: str
    partition: Literal["runId", "tenantId"]
    data_model: type[BaseModel]
    schema_version: str = SCHEMA_VERSION_EVENTS


_DEFINITIONS: tuple[EventDefinition, ...] = (
    EventDefinition("session.created", "Control Plane API", "tenantId", SessionCreatedData),
    EventDefinition("flow.run.started", "Orchestration Engine", "runId", FlowRunStartedData),
    EventDefinition("run.step.started", "Orchestration Engine", "runId", RunStepStartedData),
    EventDefinition("run.step.completed", "Orchestration Engine", "runId", RunStepCompletedData),
    EventDefinition("run.step.failed", "Orchestration Engine", "runId", RunStepFailedData),
    EventDefinition("agent.token.delta", "Agent Runtime", "runId", AgentTokenDeltaData),
    EventDefinition("run.human.requested", "Orchestration Engine", "runId", RunHumanRequestedData),
    EventDefinition("run.human.resolved", "Control Plane API", "runId", RunHumanResolvedData),
    EventDefinition("flow.run.completed", "Orchestration Engine", "runId", FlowRunCompletedData),
    EventDefinition("flow.run.failed", "Orchestration Engine", "runId", FlowRunFailedData),
    EventDefinition("run.budget.exceeded", "Agent Runtime", "runId", RunBudgetExceededData),
    EventDefinition("guardrail.violation.blocked", "Agent Runtime", "runId", GuardrailViolationBlockedData),
    EventDefinition("patch.applied", "Execution Sandbox", "runId", PatchAppliedData),
    EventDefinition("validation.gate.passed", "Execution Sandbox", "runId", ValidationGateData),
    EventDefinition("validation.gate.failed", "Execution Sandbox", "runId", ValidationGateData),
    EventDefinition("eval.run.completed", "Evaluation Service", "tenantId", EvalRunCompletedData),
    EventDefinition("plugin.installed", "Plugin Host", "tenantId", PluginLifecycleData),
    EventDefinition("plugin.removed", "Plugin Host", "tenantId", PluginLifecycleData),
    EventDefinition("agent.registered", "Registries", "tenantId", RegistryEntryData),
    EventDefinition("skill.registered", "Registries", "tenantId", RegistryEntryData),
    EventDefinition("run.timeline.planning", "Orchestration Engine", "runId", RunTimelineStepData),
    EventDefinition("run.timeline.analysis", "Orchestration Engine", "runId", RunTimelineStepData),
    EventDefinition("run.timeline.patch", "Orchestration Engine", "runId", RunTimelineStepData),
    EventDefinition("run.timeline.validation", "Orchestration Engine", "runId", RunTimelineStepData),
    EventDefinition("plan.step.reviewing", "Control Plane API", "tenantId", PlanStepTransitionData),
    EventDefinition("plan.step.approved", "Control Plane API", "tenantId", PlanStepTransitionData),
    EventDefinition("plan.step.rejected", "Control Plane API", "tenantId", PlanStepTransitionData),
    EventDefinition("plan.step.executing", "Control Plane API", "tenantId", PlanStepTransitionData),
    EventDefinition("plan.step.completed", "Control Plane API", "tenantId", PlanStepTransitionData),
)


def _build_catalog(definitions: tuple[EventDefinition, ...]) -> dict[str, EventDefinition]:
    """Index definitions by name, enforcing the naming rule and uniqueness.

    Args:
        definitions: The full set of catalog entries.

    Returns:
        Mapping of event type name to its definition.

    Raises:
        ValueError: If a name violates ``domain.entity.action`` or repeats.
    """
    catalog: dict[str, EventDefinition] = {}
    for definition in definitions:
        if not _EVENT_NAME_RE.fullmatch(definition.name):
            raise ValueError(f"Invalid event name: {definition.name!r}")
        if definition.name in catalog:
            raise ValueError(f"Duplicate event name: {definition.name!r}")
        catalog[definition.name] = definition
    return catalog


EVENT_CATALOG: dict[str, EventDefinition] = _build_catalog(_DEFINITIONS)
"""Registry of every platform event type (§14.5 catalog)."""


class EventEnvelope(BaseModel):
    """Canonical event envelope — identical on the bus, SSE, and webhooks (§14.5).

    Field names are camelCase to match the wire contract exactly, following
    the ``schemaVersion``-on-output convention of ``backend/api/v2_common.py``.
    """

    schemaVersion: str = SCHEMA_VERSION_EVENTS
    eventId: str
    type: str
    occurredAt: datetime
    tenantId: str
    partitionKey: str
    traceId: str = ""
    subject: dict[str, str] = {}
    data: dict[str, Any] = {}


def make_envelope(
    type_: str,
    *,
    tenant_id: str,
    partition_key: str,
    data: dict[str, Any],
    subject: dict[str, str] | None = None,
    trace_id: str = "",
) -> EventEnvelope:
    """Build a validated canonical envelope for a cataloged event type.

    Args:
        type_: Event type; must exist in :data:`EVENT_CATALOG`.
        tenant_id: Tenant emitting the event.
        partition_key: Ordering partition (typically the ``runId``).
        data: Payload; validated against the catalog's ``data_model``.
        subject: Identifiers of the affected resource(s).
        trace_id: W3C trace id propagated from the producing operation.

    Returns:
        The envelope, with ``data`` normalized by its payload model.

    Raises:
        KeyError: If ``type_`` is not in the catalog.
        pydantic.ValidationError: If ``data`` violates the payload schema.
    """
    definition = EVENT_CATALOG[type_]
    payload = definition.data_model.model_validate(data)
    return EventEnvelope(
        schemaVersion=definition.schema_version,
        eventId=f"evt_{uuid.uuid4().hex}",
        type=type_,
        occurredAt=datetime.now(timezone.utc),
        tenantId=tenant_id,
        partitionKey=partition_key,
        traceId=trace_id,
        subject=subject or {},
        data=payload.model_dump(),
    )


def is_compatible_evolution(old_model: type[BaseModel], new_model: type[BaseModel]) -> bool:
    """Check the additive-only payload evolution rule within a MAJOR (§14.7).

    A new payload schema is compatible when every field of the old schema
    still exists with the same requiredness, and any newly added field is
    optional. Removals and new required fields are breaking (MAJOR).

    Args:
        old_model: Currently published payload model.
        new_model: Proposed payload model.

    Returns:
        True when the change is backward compatible.
    """
    old_fields = old_model.model_fields
    new_fields = new_model.model_fields
    for name, old_field in old_fields.items():
        new_field = new_fields.get(name)
        if new_field is None or new_field.is_required() != old_field.is_required():
            return False
    return all(
        not field.is_required() for name, field in new_fields.items() if name not in old_fields
    )


__all__ = [
    "EVENT_CATALOG",
    "SCHEMA_VERSION_EVENTS",
    "EventDefinition",
    "EventEnvelope",
    "is_compatible_evolution",
    "make_envelope",
]
