"""Contract tests for the event catalog and canonical envelope (E9-S3-T1/T3)."""

from __future__ import annotations

import re

import pytest
from pydantic import BaseModel, ValidationError

from backend.events.catalog import (
    EVENT_CATALOG,
    SCHEMA_VERSION_EVENTS,
    PluginLifecycleData,
    RegistryEntryData,
    ValidationGateData,
    is_compatible_evolution,
    make_envelope,
)

_NAME_RE = re.compile(r"^[a-z]+(\.[a-z]+){1,2}$")


def test_catalog_covers_all_reference_types_with_valid_names() -> None:
    """The catalog registers the 20 §14.5 types plus additive growth, keyed and named consistently.

    The catalog is append-only (E9-S3-T1); this baseline started at the 20
    §14.5 reference types and grew by 5 with E16-S2's ``plan.step.*``
    step-approval transition events.
    """
    assert len(EVENT_CATALOG) == 25
    for name, definition in EVENT_CATALOG.items():
        assert name == definition.name
        assert _NAME_RE.fullmatch(name)
        assert definition.partition in {"runId", "tenantId"}
        assert definition.schema_version == SCHEMA_VERSION_EVENTS


def test_paired_types_share_payload_models() -> None:
    """Pairs documented with one shape in §14.5 reuse a single payload model."""
    assert EVENT_CATALOG["validation.gate.passed"].data_model is ValidationGateData
    assert EVENT_CATALOG["validation.gate.failed"].data_model is ValidationGateData
    assert EVENT_CATALOG["plugin.installed"].data_model is PluginLifecycleData
    assert EVENT_CATALOG["plugin.removed"].data_model is PluginLifecycleData
    assert EVENT_CATALOG["agent.registered"].data_model is RegistryEntryData
    assert EVENT_CATALOG["skill.registered"].data_model is RegistryEntryData


def test_make_envelope_stamps_canonical_fields() -> None:
    """The factory emits the §14.5 envelope: version, id, timestamps, partition."""
    envelope = make_envelope(
        "run.step.completed",
        tenant_id="acme",
        partition_key="run_1",
        data={"stepKey": "coder", "status": "succeeded", "attempt": 1},
        subject={"runId": "run_1", "stepKey": "coder"},
        trace_id="trace-1",
    )
    assert envelope.schemaVersion == SCHEMA_VERSION_EVENTS
    assert envelope.eventId.startswith("evt_")
    assert envelope.type == "run.step.completed"
    assert envelope.occurredAt.tzinfo is not None
    assert envelope.tenantId == "acme"
    assert envelope.partitionKey == "run_1"
    assert envelope.traceId == "trace-1"
    assert envelope.data == {"stepKey": "coder", "status": "succeeded", "attempt": 1}


def test_make_envelope_rejects_unknown_type_and_bad_payload() -> None:
    """Uncataloged types raise KeyError; schema-violating payloads raise ValidationError."""
    with pytest.raises(KeyError):
        make_envelope("no.such.event", tenant_id="t", partition_key="p", data={})
    with pytest.raises(ValidationError):
        make_envelope(
            "session.created", tenant_id="t", partition_key="p", data={"sessionId": "s"}
        )


class _V1(BaseModel):
    """Baseline payload for evolution tests."""

    stepKey: str


class _V2Additive(BaseModel):
    """Adds only an optional field: compatible (MINOR)."""

    stepKey: str
    note: str | None = None


class _V2Required(BaseModel):
    """Adds a required field: breaking (MAJOR)."""

    stepKey: str
    note: str


class _V2Removed(BaseModel):
    """Drops a published field: breaking (MAJOR)."""

    note: str | None = None


def test_evolution_rule_allows_only_additive_optional_changes() -> None:
    """§14.7: optional additions pass; removals and new required fields fail."""
    assert is_compatible_evolution(_V1, _V2Additive)
    assert not is_compatible_evolution(_V1, _V2Required)
    assert not is_compatible_evolution(_V1, _V2Removed)
