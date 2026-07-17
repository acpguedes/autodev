"""Record types, DDL, and row decoders for the durable Event Store (E8-S2).

:mod:`backend.events.store` owns the SQL and transactions; this module owns
everything pure — the stored-event/projection dataclasses, the schema
statements, the lifecycle-status mapping, and the row decoders — mirroring
the :mod:`backend.flows.records` / :mod:`backend.flows.state` split.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.events.catalog import EventEnvelope

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed"})
"""Projection statuses after which a partition receives no further events."""

STATUS_BY_EVENT: dict[str, str] = {
    "flow.run.started": "running",
    "run.step.started": "running",
    "run.step.completed": "running",
    "run.step.failed": "running",
    "run.human.requested": "waiting_human",
    "run.human.resolved": "running",
    "flow.run.completed": "completed",
    "flow.run.failed": "failed",
}
"""Projection status implied by each lifecycle event type.

Types not listed here (token deltas, timeline events, tenant-partition
events, ...) leave the projection status unchanged.
"""


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def event_store_statements(is_postgres: bool) -> tuple[str, ...]:
    """Build the CREATE TABLE/INDEX statements for the event-store schema.

    Args:
        is_postgres: Whether to emit PostgreSQL types (JSONB/TIMESTAMPTZ).

    Returns:
        The ordered DDL statements.
    """
    if is_postgres:
        json_type, time_type = "JSONB", "TIMESTAMPTZ"
    else:
        json_type, time_type = "TEXT", "TEXT"
    return (
        f"""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            partition_key TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            type TEXT NOT NULL,
            occurred_at {time_type} NOT NULL,
            trace_id TEXT NOT NULL DEFAULT '',
            subject_json {json_type},
            data_json {json_type},
            schema_version TEXT NOT NULL,
            stored_at {time_type} NOT NULL,
            UNIQUE (partition_key, sequence)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS event_projections (
            partition_key TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            status TEXT NOT NULL DEFAULT '',
            last_sequence INTEGER NOT NULL,
            last_event_type TEXT NOT NULL,
            last_event_at {time_type} NOT NULL,
            counts_json {json_type},
            updated_at {time_type} NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_tenant ON events(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_events_stored ON events(stored_at)",
        (
            "CREATE INDEX IF NOT EXISTS idx_event_projections_tenant "
            "ON event_projections(tenant_id, status)"
        ),
    )


@dataclass(frozen=True)
class StoredEvent:
    """One durably stored envelope with its per-partition position.

    Attributes:
        sequence: 1-based position within the partition's append order.
        envelope: The canonical envelope as originally published.
        stored_at: ISO-8601 UTC instant the append transaction committed.
    """

    sequence: int
    envelope: EventEnvelope
    stored_at: str


@dataclass(frozen=True)
class EventProjection:
    """Materialized per-partition summary for fast status queries (T3).

    Attributes:
        partition_key: The partition (typically a run id).
        tenant_id: Tenant of the partition's events.
        status: Derived lifecycle status (see :data:`STATUS_BY_EVENT`);
            empty when no status-bearing event was seen.
        last_sequence: Sequence of the most recent stored event.
        last_event_type: Type of the most recent stored event.
        last_event_at: ``occurredAt`` of the most recent stored event.
        counts: Number of stored events per event type. Counts survive
            compaction — they describe everything the partition ever
            emitted, not merely the rows currently retained.
        updated_at: ISO-8601 UTC instant of the last projection update.
    """

    partition_key: str
    tenant_id: str
    status: str
    last_sequence: int
    last_event_type: str
    last_event_at: str
    counts: dict[str, int] = field(default_factory=dict)
    updated_at: str = ""

    def to_document(self) -> dict[str, Any]:
        """Render the projection as a JSON-serializable document.

        Returns:
            A dict suitable for API responses.
        """
        return {
            "schemaVersion": "1",
            "partitionKey": self.partition_key,
            "tenantId": self.tenant_id,
            "status": self.status,
            "lastSequence": self.last_sequence,
            "lastEventType": self.last_event_type,
            "lastEventAt": self.last_event_at,
            "counts": dict(self.counts),
            "updatedAt": self.updated_at,
        }


def _iso(value: Any) -> str:
    """Normalize a DB timestamp value (datetime or str) to an ISO string.

    Args:
        value: Raw column value.

    Returns:
        The ISO-8601 string form.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def decode_event(row: Any) -> StoredEvent:
    """Decode an ``events`` row into a :class:`StoredEvent`.

    Args:
        row: Row in the column order ``sequence, stored_at, event_id, type,
            occurred_at, tenant_id, partition_key, trace_id, subject_json,
            data_json, schema_version``.

    Returns:
        The decoded stored event.
    """
    values = list(row)
    subject = values[8]
    data = values[9]
    envelope = EventEnvelope(
        schemaVersion=str(values[10]),
        eventId=str(values[2]),
        type=str(values[3]),
        occurredAt=_iso(values[4]),
        tenantId=str(values[5]),
        partitionKey=str(values[6]),
        traceId=str(values[7] or ""),
        subject=json.loads(subject) if isinstance(subject, str) else (subject or {}),
        data=json.loads(data) if isinstance(data, str) else (data or {}),
    )
    return StoredEvent(
        sequence=int(values[0]), envelope=envelope, stored_at=_iso(values[1])
    )


def decode_projection(row: Any) -> EventProjection:
    """Decode an ``event_projections`` row into an :class:`EventProjection`.

    Args:
        row: Row in the column order ``partition_key, tenant_id, status,
            last_sequence, last_event_type, last_event_at, counts_json,
            updated_at``.

    Returns:
        The decoded projection.
    """
    values = list(row)
    counts = values[6]
    return EventProjection(
        partition_key=str(values[0]),
        tenant_id=str(values[1]),
        status=str(values[2] or ""),
        last_sequence=int(values[3]),
        last_event_type=str(values[4]),
        last_event_at=_iso(values[5]),
        counts=json.loads(counts) if isinstance(counts, str) else (counts or {}),
        updated_at=_iso(values[7]),
    )


__all__ = [
    "STATUS_BY_EVENT",
    "TERMINAL_STATUSES",
    "EventProjection",
    "StoredEvent",
    "decode_event",
    "decode_projection",
    "event_store_statements",
    "utcnow_iso",
]
