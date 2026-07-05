"""Durable Run/Step/Event store for flow executions.

Record types live in :mod:`backend.flows.records`; this module owns the SQL.
Every flow run, step activation, and lifecycle event persists in the platform
state store (SQLite locally, PostgreSQL in production). The ordered
``flow_events`` table doubles as the event store that deterministic replay
(E3-S3) reads back.
"""

from __future__ import annotations

import json
import uuid
from contextlib import closing
from typing import Any

from backend.flows.records import (
    RUN_STATUSES,
    STEP_STATUSES,
    FlowEventRecord,
    FlowRunRecord,
    FlowStepRecord,
    _utcnow,
    decode_event,
    decode_run,
    decode_step,
)
from backend.flows.schema_sql import flow_state_statements
from backend.persistence.database import get_store

class FlowRunStore:
    """Durable store for flow runs, steps, and ordered events."""

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
            raise TypeError("FlowRunStore requires a durable store with connect()")
        self._ensure_schema()

    def _connect(self) -> Any:
        """Open a store connection tuned for concurrent flow writers.

        On SQLite, sets a generous busy timeout so concurrent runs queue on
        the write lock instead of failing with ``database is locked``.

        Returns:
            A DB-API connection from the underlying store.
        """
        conn = self._store.connect()
        if not self._is_postgres:
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _begin_write(self, conn: Any) -> None:
        """Start a write transaction eagerly on SQLite.

        ``create_step``/``append_event`` read the current maximum sequence and
        then insert; on SQLite that read-then-write pattern in a deferred
        transaction can hit an upgrade deadlock under concurrency. Taking the
        write lock upfront (``BEGIN IMMEDIATE``) serializes writers safely.

        Args:
            conn: Connection returned by :meth:`_connect`.
        """
        if not self._is_postgres:
            conn.execute("BEGIN IMMEDIATE")

    # ------------------------------------------------------------------ runs

    def create_run(
        self,
        *,
        flow_id: str,
        flow_version: str,
        tenant_id: str = "default",
        trigger: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        run_id: str | None = None,
    ) -> FlowRunRecord:
        """Persist a new run in ``pending`` status.

        Args:
            flow_id: Fully qualified flow id.
            flow_version: Resolved flow version.
            tenant_id: Tenant the run is scoped to.
            trigger: Normalized trigger document.
            input: Run input payload.
            state: Initial durable state.
            parent_run_id: Parent run id for sub-flow runs.
            run_id: Identifier to use; generated when omitted.

        Returns:
            The persisted :class:`FlowRunRecord`.
        """
        record = FlowRunRecord(
            run_id=run_id or str(uuid.uuid4()),
            flow_id=flow_id,
            flow_version=flow_version,
            tenant_id=tenant_id,
            status="pending",
            trigger=dict(trigger or {}),
            input=dict(input or {}),
            state=dict(state or {}),
            parent_run_id=parent_run_id,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        sql = self._sql(
            """
            INSERT INTO flow_runs (
                run_id, flow_id, flow_version, tenant_id, status, stop_reason,
                trigger_json, input_json, state_json, output_json,
                parent_run_id, created_at, updated_at
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
        )
        with closing(self._connect()) as conn:
            conn.execute(
                sql,
                (
                    record.run_id,
                    record.flow_id,
                    record.flow_version,
                    record.tenant_id,
                    record.status,
                    record.stop_reason,
                    json.dumps(record.trigger),
                    json.dumps(record.input),
                    json.dumps(record.state),
                    json.dumps(None),
                    record.parent_run_id,
                    record.created_at,
                    record.updated_at,
                ),
            )
            conn.commit()
        return record

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        stop_reason: str | None = None,
        state: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
    ) -> None:
        """Update mutable fields of a run.

        Args:
            run_id: Id of the run to update.
            status: New status, when changing; must be in :data:`RUN_STATUSES`.
            stop_reason: New stop reason, when changing.
            state: New durable state document, when changing.
            output: Consolidated output, when the run completes.

        Raises:
            ValueError: If ``status`` is not a known run status.
        """
        if status is not None and status not in RUN_STATUSES:
            raise ValueError(f"unknown run status {status!r}")
        assignments: list[str] = ["updated_at = {p}"]
        params: list[Any] = [_utcnow()]
        if status is not None:
            assignments.append("status = {p}")
            params.append(status)
        if stop_reason is not None:
            assignments.append("stop_reason = {p}")
            params.append(stop_reason)
        if state is not None:
            assignments.append("state_json = {p}")
            params.append(json.dumps(state))
        if output is not None:
            assignments.append("output_json = {p}")
            params.append(json.dumps(output))
        sql = self._sql(
            "UPDATE flow_runs SET " + ", ".join(assignments) + " WHERE run_id = {p}"
        )
        params.append(run_id)
        with closing(self._connect()) as conn:
            conn.execute(sql, tuple(params))
            conn.commit()

    def get_run(self, run_id: str) -> FlowRunRecord | None:
        """Fetch a run by id.

        Args:
            run_id: Id of the run.

        Returns:
            The run record, or ``None`` when unknown.
        """
        sql = self._sql("SELECT * FROM flow_runs WHERE run_id = {p}")
        with closing(self._connect()) as conn:
            row = conn.execute(sql, (run_id,)).fetchone()
        return decode_run(row) if row is not None else None

    def list_runs(
        self,
        *,
        flow_id: str | None = None,
        status: str | None = None,
        parent_run_id: str | None = None,
    ) -> list[FlowRunRecord]:
        """List runs, optionally filtered by flow id, status, and/or parent.

        Args:
            flow_id: Restrict to runs of this flow.
            status: Restrict to runs in this status.
            parent_run_id: Restrict to child runs of this parent run
                (hierarchical trace of composite nodes, E3-S5).

        Returns:
            Matching runs, most recent first.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if flow_id is not None:
            clauses.append("flow_id = {p}")
            params.append(flow_id)
        if status is not None:
            clauses.append("status = {p}")
            params.append(status)
        if parent_run_id is not None:
            clauses.append("parent_run_id = {p}")
            params.append(parent_run_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = self._sql(
            f"SELECT * FROM flow_runs{where} ORDER BY created_at DESC, run_id"
        )
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [decode_run(row) for row in rows]

    # ----------------------------------------------------------------- steps

    def create_step(
        self,
        *,
        run_id: str,
        node_id: str,
        node_type: str,
        attempt: int,
        input: dict[str, Any] | None = None,
    ) -> FlowStepRecord:
        """Persist a new step activation in ``running`` status.

        Args:
            run_id: Run the step belongs to.
            node_id: Id of the node being activated.
            node_type: Type of the node being activated.
            attempt: 1-based attempt counter.
            input: Rendered input passed to the node.

        Returns:
            The persisted :class:`FlowStepRecord`.
        """
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            row = conn.execute(
                self._sql(
                    "SELECT COALESCE(MAX(sequence), 0) FROM flow_steps WHERE run_id = {p}"
                ),
                (run_id,),
            ).fetchone()
            sequence = int(row[0] if not hasattr(row, "keys") else list(row)[0]) + 1
            record = FlowStepRecord(
                step_id=str(uuid.uuid4()),
                run_id=run_id,
                node_id=node_id,
                node_type=node_type,
                status="running",
                attempt=attempt,
                input=dict(input or {}),
                started_at=_utcnow(),
                sequence=sequence,
            )
            conn.execute(
                self._sql(
                    """
                    INSERT INTO flow_steps (
                        step_id, run_id, node_id, node_type, status, attempt,
                        input_json, output_json, error, started_at, completed_at,
                        sequence
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    """
                ),
                (
                    record.step_id,
                    record.run_id,
                    record.node_id,
                    record.node_type,
                    record.status,
                    record.attempt,
                    json.dumps(record.input),
                    json.dumps(None),
                    record.error,
                    record.started_at,
                    record.completed_at,
                    record.sequence,
                ),
            )
            conn.commit()
        return record

    def complete_step(
        self,
        step_id: str,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        """Mark a step as finished.

        Args:
            step_id: Id of the step to finish.
            status: Terminal status, one of :data:`STEP_STATUSES`.
            output: Output produced by the node, when completed.
            error: Failure detail, when failed.

        Raises:
            ValueError: If ``status`` is not a known step status.
        """
        if status not in STEP_STATUSES:
            raise ValueError(f"unknown step status {status!r}")
        sql = self._sql(
            """
            UPDATE flow_steps
            SET status = {p}, output_json = {p}, error = {p}, completed_at = {p}
            WHERE step_id = {p}
            """
        )
        with closing(self._connect()) as conn:
            conn.execute(
                sql, (status, json.dumps(output), error, _utcnow(), step_id)
            )
            conn.commit()

    def list_steps(self, run_id: str) -> list[FlowStepRecord]:
        """List a run's steps in activation order.

        Args:
            run_id: Id of the run.

        Returns:
            The run's steps ordered by sequence.
        """
        sql = self._sql(
            "SELECT * FROM flow_steps WHERE run_id = {p} ORDER BY sequence"
        )
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, (run_id,)).fetchall()
        return [decode_step(row) for row in rows]

    # ---------------------------------------------------------------- events

    def append_event(
        self, *, run_id: str, name: str, payload: dict[str, Any] | None = None
    ) -> FlowEventRecord:
        """Append an ordered lifecycle event to the run's event store.

        Args:
            run_id: Run the event belongs to.
            name: Event name (``domain.entity.action``, past tense).
            payload: Event payload.

        Returns:
            The persisted :class:`FlowEventRecord`.
        """
        with closing(self._connect()) as conn:
            self._begin_write(conn)
            row = conn.execute(
                self._sql(
                    "SELECT COALESCE(MAX(sequence), 0) FROM flow_events WHERE run_id = {p}"
                ),
                (run_id,),
            ).fetchone()
            sequence = int(row[0] if not hasattr(row, "keys") else list(row)[0]) + 1
            record = FlowEventRecord(
                event_id=str(uuid.uuid4()),
                run_id=run_id,
                sequence=sequence,
                name=name,
                payload=dict(payload or {}),
                created_at=_utcnow(),
            )
            conn.execute(
                self._sql(
                    """
                    INSERT INTO flow_events (
                        event_id, run_id, sequence, name, payload_json, created_at
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p})
                    """
                ),
                (
                    record.event_id,
                    record.run_id,
                    record.sequence,
                    record.name,
                    json.dumps(record.payload),
                    record.created_at,
                ),
            )
            conn.commit()
        return record

    def list_events(self, run_id: str) -> list[FlowEventRecord]:
        """List a run's events in emission order.

        Args:
            run_id: Id of the run.

        Returns:
            The run's events ordered by sequence.
        """
        sql = self._sql(
            "SELECT * FROM flow_events WHERE run_id = {p} ORDER BY sequence"
        )
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, (run_id,)).fetchall()
        return [decode_event(row) for row in rows]

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

    def _ensure_schema(self) -> None:
        """Create the flow run/step/event tables if they do not exist."""
        with closing(self._connect()) as conn:
            for statement in flow_state_statements(self._is_postgres):
                conn.execute(statement)
            conn.commit()


__all__ = [
    "FlowEventRecord",
    "FlowRunRecord",
    "FlowRunStore",
    "FlowStepRecord",
    "RUN_STATUSES",
    "STEP_STATUSES",
]
