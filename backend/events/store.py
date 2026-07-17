"""Durable Event Store for canonical envelopes (E8-S2, reference §18.7.2).

The Event Bus (:mod:`backend.events.bus`) delivers
:class:`~backend.events.catalog.EventEnvelope` instances at-least-once but
only the Redis backend retains them, and only until the stream is trimmed.
This module gives every published envelope a durable, append-only home in the
State Store (SQLite locally, PostgreSQL in production), ordered per partition
(``partitionKey`` — typically a ``runId``), so that:

* a run's full event history survives process restarts and bus backend
  changes (E8-S2-T1);
* a run can be *reconstructed* purely from its stored events
  (:func:`EventStore.reconstruct_run`, E8-S2-T2) — complementing the
  flow-state checkpoint replay of :mod:`backend.flows.checkpoint`;
* current status is answerable in O(1) from the ``event_projections``
  materialization, updated in the same transaction as each append
  (E8-S2-T3);
* storage is bounded by a configurable retention window
  (:func:`EventStore.purge_expired`, E8-S2-T4): events of *terminal*
  partitions older than the window are compacted away while their
  projection row is kept as the durable summary.

Writes are intentionally small (one INSERT + one UPSERT per event) so the
append never becomes a bottleneck for the run itself; the store is attached
to the bus as a regular subscriber, and subscriber failures are isolated by
the bus (a persistence hiccup never blocks delivery or the run — E8-S2 CNF).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.events.catalog import EventEnvelope
from backend.events.records import (
    STATUS_BY_EVENT,
    TERMINAL_STATUSES,
    EventProjection,
    StoredEvent,
    decode_event,
    decode_projection,
    event_store_statements,
    utcnow_iso,
)
from backend.persistence.database import get_store


class EventStore:
    """Append-only State Store persistence for canonical envelopes.

    Follows the same store/dialect conventions as
    :class:`backend.flows.state.FlowRunStore` (shared durable store, ``{p}``
    placeholder substitution, eager write transactions on SQLite).
    """

    def __init__(self, store: Any | None = None) -> None:
        """Initialize the store, ensuring its backing schema exists.

        Args:
            store: Durable store to use; defaults to the process-wide store
                from :func:`backend.persistence.database.get_store`.

        Raises:
            TypeError: If ``store`` does not expose a ``connect()`` method.
        """
        self._store = store or get_store()
        if not hasattr(self._store, "connect"):
            raise TypeError("EventStore requires a durable store with connect()")
        self._local = threading.local()
        self._ensure_schema()

    @property
    def backing_store(self) -> Any:
        """The durable store this Event Store writes to."""
        return self._store

    # --------------------------------------------------------------- append

    def append(self, envelope: EventEnvelope) -> StoredEvent:
        """Durably append an envelope to its partition, updating projections.

        The event INSERT and the projection UPSERT commit in one transaction,
        so the materialization can never lag or disagree with the log (T3).

        Args:
            envelope: Validated envelope from
                :func:`backend.events.catalog.make_envelope`.

        Returns:
            The :class:`StoredEvent` with its assigned sequence.
        """
        stored_at = utcnow_iso()
        conn = self._connect()
        try:
            self._begin_write(conn)
            row = conn.execute(
                self._sql(
                    "SELECT COALESCE(MAX(sequence), 0) FROM events "
                    "WHERE partition_key = {p}"
                ),
                (envelope.partitionKey,),
            ).fetchone()
            sequence = int(row[0] if not hasattr(row, "keys") else list(row)[0]) + 1
            conn.execute(
                self._sql(
                    """
                    INSERT INTO events (
                        event_id, tenant_id, partition_key, sequence, type,
                        occurred_at, trace_id, subject_json, data_json,
                        schema_version, stored_at
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    """
                ),
                (
                    envelope.eventId,
                    envelope.tenantId,
                    envelope.partitionKey,
                    sequence,
                    envelope.type,
                    envelope.occurredAt.isoformat(),
                    envelope.traceId,
                    json.dumps(envelope.subject),
                    json.dumps(envelope.data),
                    envelope.schemaVersion,
                    stored_at,
                ),
            )
            self._upsert_projection(conn, envelope, sequence, stored_at)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            finally:
                self._drop_connection()
            raise
        return StoredEvent(sequence=sequence, envelope=envelope, stored_at=stored_at)

    def _upsert_projection(
        self, conn: Any, envelope: EventEnvelope, sequence: int, updated_at: str
    ) -> None:
        """Fold one appended envelope into its partition's projection row.

        Args:
            conn: Open connection of the append transaction.
            envelope: The envelope just inserted.
            sequence: The sequence assigned to the envelope.
            updated_at: Timestamp shared with the event's ``stored_at``.
        """
        row = conn.execute(
            self._sql(
                "SELECT status, counts_json FROM event_projections "
                "WHERE partition_key = {p}"
            ),
            (envelope.partitionKey,),
        ).fetchone()
        if row is None:
            status, counts = "", {}
        else:
            values = list(row)
            status = str(values[0] or "")
            counts = json.loads(values[1]) if values[1] else {}
        status = STATUS_BY_EVENT.get(envelope.type, status)
        counts[envelope.type] = int(counts.get(envelope.type, 0)) + 1
        params = (
            envelope.tenantId,
            status,
            sequence,
            envelope.type,
            envelope.occurredAt.isoformat(),
            json.dumps(counts),
            updated_at,
            envelope.partitionKey,
        )
        if row is None:
            conn.execute(
                self._sql(
                    """
                    INSERT INTO event_projections (
                        tenant_id, status, last_sequence, last_event_type,
                        last_event_at, counts_json, updated_at, partition_key
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    """
                ),
                params,
            )
        else:
            conn.execute(
                self._sql(
                    """
                    UPDATE event_projections
                    SET tenant_id = {p}, status = {p}, last_sequence = {p},
                        last_event_type = {p}, last_event_at = {p},
                        counts_json = {p}, updated_at = {p}
                    WHERE partition_key = {p}
                    """
                ),
                params,
            )

    # ---------------------------------------------------------------- reads

    def list_events(
        self, partition_key: str, *, after_sequence: int | None = None
    ) -> list[StoredEvent]:
        """List a partition's stored events in append order.

        Args:
            partition_key: Partition to read.
            after_sequence: Exclusive-start sequence; ``None`` reads from the
                beginning.

        Returns:
            Ordered stored events strictly after ``after_sequence``.
        """
        sql = self._sql(
            "SELECT sequence, stored_at, event_id, type, occurred_at, tenant_id, "
            "partition_key, trace_id, subject_json, data_json, schema_version "
            "FROM events WHERE partition_key = {p} AND sequence > {p} "
            "ORDER BY sequence"
        )
        rows = (
            self._connect()
            .execute(sql, (partition_key, after_sequence or 0))
            .fetchall()
        )
        return [decode_event(row) for row in rows]

    def get_projection(self, partition_key: str) -> EventProjection | None:
        """Fetch a partition's materialized summary (T3, O(1) status query).

        Args:
            partition_key: Partition to summarize.

        Returns:
            The projection, or ``None`` when the partition has no events.
        """
        sql = self._sql(
            "SELECT partition_key, tenant_id, status, last_sequence, "
            "last_event_type, last_event_at, counts_json, updated_at "
            "FROM event_projections WHERE partition_key = {p}"
        )
        row = self._connect().execute(sql, (partition_key,)).fetchone()
        return decode_projection(row) if row is not None else None

    def list_projections(
        self, *, tenant_id: str | None = None, status: str | None = None
    ) -> list[EventProjection]:
        """List projections, optionally filtered by tenant and/or status.

        Args:
            tenant_id: Restrict to partitions of this tenant.
            status: Restrict to partitions in this derived status.

        Returns:
            Matching projections, most recently updated first.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_id is not None:
            clauses.append("tenant_id = {p}")
            params.append(tenant_id)
        if status is not None:
            clauses.append("status = {p}")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = self._sql(
            "SELECT partition_key, tenant_id, status, last_sequence, "
            "last_event_type, last_event_at, counts_json, updated_at "
            f"FROM event_projections{where} "
            "ORDER BY updated_at DESC, partition_key"
        )
        rows = self._connect().execute(sql, tuple(params)).fetchall()
        return [decode_projection(row) for row in rows]

    # -------------------------------------------------------- reconstruction

    def reconstruct_run(self, partition_key: str) -> dict[str, Any]:
        """Rebuild a run view purely from its stored events (T2).

        Folds the partition's events, in order, into a document describing
        the run's lifecycle: derived status, per-step activation trail, and
        terminal outcome. The view is a pure function of the event log — no
        ``flow_runs``/``flow_steps`` row is consulted — which is what makes
        the event store a genuine reconstruction source rather than a cache.

        Args:
            partition_key: The run's partition (its run id).

        Returns:
            A JSON-serializable document with ``status``, ``steps`` (ordered
            step activations with their terminal state), ``startedAt``/
            ``endedAt``, ``output``-adjacent terminal fields (``costUsd``,
            ``tokens``, ``error``), and ``eventCount``.
        """
        events = self.list_events(partition_key)
        status = ""
        started_at = ""
        ended_at = ""
        error = ""
        cost_usd = 0.0
        tokens = 0
        steps: list[dict[str, Any]] = []
        open_steps: dict[str, dict[str, Any]] = {}
        for stored in events:
            envelope = stored.envelope
            status = STATUS_BY_EVENT.get(envelope.type, status)
            data = envelope.data
            if envelope.type == "flow.run.started":
                started_at = envelope.occurredAt.isoformat()
            elif envelope.type == "run.step.started":
                step = {
                    "stepKey": str(data.get("stepKey", "")),
                    "agent": str(data.get("agent", "")),
                    "status": "running",
                    "attempt": 1,
                    "sequence": stored.sequence,
                }
                steps.append(step)
                open_steps[step["stepKey"]] = step
            elif envelope.type in ("run.step.completed", "run.step.failed"):
                key = str(data.get("stepKey", ""))
                step = open_steps.get(key)
                if step is None:
                    step = {"stepKey": key, "agent": "", "sequence": stored.sequence}
                    steps.append(step)
                terminal = (
                    str(data.get("status", "completed"))
                    if envelope.type == "run.step.completed"
                    else "failed"
                )
                step["status"] = terminal
                step["attempt"] = int(data.get("attempt", 1))
                if envelope.type == "run.step.failed":
                    step["error"] = str(data.get("error", ""))
            elif envelope.type == "flow.run.completed":
                ended_at = envelope.occurredAt.isoformat()
                status = str(data.get("status", "completed"))
                cost_usd = float(data.get("costUsd", 0.0))
                tokens = int(data.get("tokens", 0))
            elif envelope.type == "flow.run.failed":
                ended_at = envelope.occurredAt.isoformat()
                error = str(data.get("error", ""))
        return {
            "schemaVersion": "1",
            "runId": partition_key,
            "status": status,
            "startedAt": started_at,
            "endedAt": ended_at,
            "error": error,
            "costUsd": cost_usd,
            "tokens": tokens,
            "steps": steps,
            "eventCount": len(events),
        }

    # ------------------------------------------------------------- retention

    def purge_expired(self, *, retention_days: int, now: datetime | None = None) -> int:
        """Compact events of terminal partitions past the retention window (T4).

        Only partitions whose projection status is terminal
        (:data:`TERMINAL_STATUSES`) are eligible: an active run keeps its
        full log regardless of age. Eligible partitions have every event row
        older than the cutoff deleted; the projection row is always kept as
        the compacted summary (status, counts, last sequence survive).

        Args:
            retention_days: Number of days to retain events after they are
                stored. Values ``< 0`` disable purging entirely.
            now: Clock override for tests; defaults to the current UTC time.

        Returns:
            The number of event rows deleted.
        """
        if retention_days < 0:
            return 0
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
        cutoff_iso = cutoff.isoformat()
        sql = self._sql(
            """
            DELETE FROM events
            WHERE stored_at < {p}
              AND partition_key IN (
                SELECT partition_key FROM event_projections
                WHERE status IN ({terminal})
              )
            """.replace(
                "{terminal}", ", ".join("{p}" for _ in sorted(TERMINAL_STATUSES))
            )
        )
        conn = self._connect()
        try:
            self._begin_write(conn)
            cursor = conn.execute(sql, (cutoff_iso, *sorted(TERMINAL_STATUSES)))
            deleted = int(cursor.rowcount if cursor.rowcount is not None else 0)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            finally:
                self._drop_connection()
            raise
        return deleted

    # --------------------------------------------------------------- helpers

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        url = str(getattr(self._store, "database_url", ""))
        return url.startswith(("postgresql://", "postgres://"))

    def _sql(self, template: str) -> str:
        """Substitute the dialect placeholder into a SQL template.

        Args:
            template: SQL text using ``{p}`` for parameter placeholders.

        Returns:
            The SQL with dialect-appropriate placeholders.
        """
        return template.format(p="%s" if self._is_postgres else "?")

    def _connect(self) -> Any:
        """Return this thread's cached store connection, creating it once.

        Appends happen on every published event, so paying a connection
        open (plus SQLite's WAL pragma, a write) per event would dominate
        the append cost by orders of magnitude and violate the story's
        fast-append CNF. Each thread therefore opens one connection lazily
        and reuses it; SQLite connections are not shareable across threads
        (``check_same_thread``), which is why the cache is per-thread
        rather than per-store.

        Returns:
            A DB-API connection from the underlying store.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._store.connect()
            if not self._is_postgres:
                conn.execute("PRAGMA busy_timeout=15000")
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def _drop_connection(self) -> None:
        """Discard this thread's cached connection after a failure.

        The next operation reconnects lazily, so a broken connection (a
        rolled-over Postgres session, a deleted SQLite file in tests) heals
        instead of poisoning every subsequent append.
        """
        conn = getattr(self._local, "conn", None)
        self._local.conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - already discarding
                pass

    def _begin_write(self, conn: Any) -> None:
        """Start a write transaction eagerly on SQLite.

        :meth:`append` reads the partition's maximum sequence and then
        inserts; taking the SQLite write lock upfront (``BEGIN IMMEDIATE``)
        avoids upgrade deadlocks under concurrent appends, mirroring
        :class:`backend.flows.state.FlowRunStore`.

        Args:
            conn: Connection returned by :meth:`_connect`.
        """
        if not self._is_postgres:
            conn.execute("BEGIN IMMEDIATE")

    def _ensure_schema(self) -> None:
        """Create the event-store tables if they do not exist."""
        conn = self._connect()
        for statement in event_store_statements(self._is_postgres):
            conn.execute(statement)
        conn.commit()


__all__ = [
    "EventProjection",
    "EventStore",
    "StoredEvent",
    "TERMINAL_STATUSES",
]
