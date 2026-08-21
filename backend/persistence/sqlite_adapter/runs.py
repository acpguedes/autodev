"""SQLite RunRepository implementation."""

from __future__ import annotations

import sqlite3
from typing import Any

from backend.persistence.codecs import (
    build_run_record,
    build_step_record,
    dumps_json,
    group_steps_by_run,
    loads_json,
    prepare_step_batch,
)
from backend.persistence.sqlite_adapter._shared import _ConnectionOwner
from backend.persistence.tenancy import DEFAULT_TENANT_ID, sqlite_tenant_clause


class _RunsMixin(_ConnectionOwner):
    """``runs`` and ``run_steps`` table read/write, scoped per-tenant via a hand-written WHERE clause."""

    def create_run(
        self,
        *,
        run_id: str,
        session_id: str,
        status: str,
        run_type: str,
        current_state: str,
        trigger_message: str,
        results: list[dict[str, Any]],
        steps: list[dict[str, Any]],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Insert a new run row (and its steps) scoped to *tenant_id*.

        Args:
            run_id: Unique identifier for the run.
            session_id: Identifier of the owning session.
            status: Current run status.
            run_type: Kind of run being executed.
            current_state: Current flow/state machine state.
            trigger_message: Message that triggered the run.
            results: Ordered list of result documents produced so far.
            steps: Ordered list of step records to persist alongside the run.
            tenant_id: Tenant the new run belongs to.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, session_id, status, run_type, current_state, "
                "trigger_message, results_json, tenant_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    session_id,
                    status,
                    run_type,
                    current_state,
                    trigger_message,
                    dumps_json(results),
                    tenant_id,
                ),
            )
            self._persist_run_steps(conn, run_id, steps)
            conn.commit()

    def update_run(
        self,
        *,
        run_id: str,
        status: str,
        current_state: str,
        results: list[dict[str, Any]],
        steps: list[dict[str, Any]],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Update a run's status, state, results, and steps, scoped to *tenant_id*."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE runs SET status = ?, current_state = ?, results_json = ?, "
                f"completed_at = CURRENT_TIMESTAMP WHERE id = ? {clause}",
                (status, current_state, dumps_json(results), run_id, *params),
            )
            self._persist_run_steps(conn, run_id, steps)
            conn.commit()

    def list_runs(
        self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List all runs for a session scoped to *tenant_id*, most recently created first."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM runs WHERE session_id = ? {clause} ORDER BY rowid DESC",
                (session_id, *params),
            ).fetchall()
            steps_by_run = self._fetch_steps_for_runs(conn, [row["id"] for row in rows])
        return [self._decode_run(row, steps_by_run.get(row["id"], [])) for row in rows]

    def list_runs_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of a session's runs plus its total run count (E44-S3).

        Ordering matches :meth:`list_runs` exactly; only the windowing moves
        from the API layer into SQL.

        Args:
            session_id: Session whose runs should be listed.
            limit: Maximum number of runs to return.
            offset: Number of runs to skip, in listing order.
            tenant_id: Tenant to scope the listing to.

        Returns:
            A ``(page, total)`` pair, each page record shaped exactly as
            :meth:`list_runs` returns.
        """
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM runs WHERE session_id = ? {clause}",
                    (session_id, *params),
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"SELECT * FROM runs WHERE session_id = ? {clause} ORDER BY rowid DESC "
                f"LIMIT ? OFFSET ?",
                (session_id, *params, limit, offset),
            ).fetchall()
            steps_by_run = self._fetch_steps_for_runs(conn, [row["id"] for row in rows])
        return [self._decode_run(row, steps_by_run.get(row["id"], [])) for row in rows], total

    def get_run(
        self, run_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, Any] | None:
        """Fetch a single run by its primary key, scoped to *tenant_id* (E44-S1).

        The session-agnostic counterpart to :meth:`list_runs`: it resolves a
        run without knowing which session owns it, so callers holding only a
        run id (e.g. ``GET /v2/turns/{turn_id}``) no longer have to scan every
        session's runs. Costs exactly two statements on one connection — the
        indexed primary-key lookup plus one batched step query.

        Args:
            run_id: Identifier of the run to fetch.
            tenant_id: Tenant the run must belong to; a run owned by another
                tenant is indistinguishable from a nonexistent one.

        Returns:
            The decoded run record, or ``None`` when no run with that id
            exists within *tenant_id*'s scope.
        """
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT * FROM runs WHERE id = ? {clause}", (run_id, *params)
            ).fetchone()
            if row is None:
                return None
            steps = self._fetch_steps_for_runs(conn, [run_id]).get(run_id, [])
        return self._decode_run(row, steps)

    def list_run_steps(
        self, run_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List all steps recorded for a run, in execution order.

        ``run_steps`` has no ``tenant_id`` column of its own (ADR-010); it is
        scoped transitively via a ``JOIN`` against its parent ``runs`` row.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT rs.step_key, rs.agent, rs.status, rs.started_at, rs.completed_at, rs.attempt "
                "FROM run_steps rs JOIN runs r ON rs.run_id = r.id "
                "WHERE rs.run_id = ? AND r.tenant_id = ? ORDER BY rs.position ASC, rs.id ASC",
                (run_id, tenant_id),
            ).fetchall()
        return [
            build_step_record(
                step_key=row["step_key"],
                agent=row["agent"],
                status=row["status"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                attempt=row["attempt"],
            )
            for row in rows
        ]

    @staticmethod
    def _decode_run(row: sqlite3.Row, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Decode one ``runs`` row into the store's public dict shape.

        Pure by design (E44-S1): steps are passed in already fetched, so
        decoding never issues a query — and never opens a connection — of its
        own.

        Args:
            row: The raw ``runs`` row.
            steps: The run's already-fetched step records, in execution order.

        Returns:
            The decoded run record.
        """
        return build_run_record(
            id=row["id"],
            session_id=row["session_id"],
            status=row["status"],
            run_type=row["run_type"],
            current_state=row["current_state"],
            trigger_message=row["trigger_message"],
            results=loads_json(row["results_json"]),
            steps=steps,
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _fetch_steps_for_runs(
        conn: sqlite3.Connection, run_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Load every step of *run_ids* in one query, grouped by run id (E44-S1).

        The caller has already scoped ``run_ids`` to a tenant by selecting
        them from a tenant-filtered ``runs`` query, so no further tenant
        predicate is needed here (``run_steps`` has no ``tenant_id`` column of
        its own — ADR-010).

        Args:
            conn: An open connection to reuse; no new connection is opened.
            run_ids: Run identifiers whose steps should be loaded.

        Returns:
            A mapping of run id to its steps in execution order. Runs with no
            steps are absent from the mapping.
        """
        if not run_ids:
            return {}
        placeholders = ", ".join("?" for _ in run_ids)
        rows = conn.execute(
            "SELECT run_id, step_key, agent, status, started_at, completed_at, attempt "
            f"FROM run_steps WHERE run_id IN ({placeholders}) ORDER BY position ASC, id ASC",
            tuple(run_ids),
        ).fetchall()
        return group_steps_by_run(
            (
                row["run_id"],
                build_step_record(
                    step_key=row["step_key"],
                    agent=row["agent"],
                    status=row["status"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    attempt=row["attempt"],
                ),
            )
            for row in rows
        )

    @staticmethod
    def _persist_run_steps(
        conn: sqlite3.Connection, run_id: str, steps: list[dict[str, Any]]
    ) -> None:
        """Persist a run's ordered step list incrementally (E44-S5).

        Upserts each step onto its ``(run_id, position)`` key and skips the
        ``DO UPDATE`` when nothing about the row changed, so a checkpoint that
        adds the Nth step writes one row rather than deleting and re-inserting
        all N. Trailing rows beyond the current list length are trimmed, which
        is what makes a shortened list (e.g. a resumed run dropping its
        ``awaiting_approval`` placeholder) converge.

        Args:
            conn: An open connection inside the caller's transaction.
            run_id: Run whose steps are being persisted.
            steps: The run's full ordered step list.
        """
        conn.execute(
            "DELETE FROM run_steps WHERE run_id = ? AND position >= ?", (run_id, len(steps))
        )
        if not steps:
            return
        conn.executemany(
            "INSERT INTO run_steps "
            "(run_id, position, step_key, agent, status, started_at, completed_at, attempt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, position) DO UPDATE SET "
            "step_key = excluded.step_key, agent = excluded.agent, status = excluded.status, "
            "started_at = excluded.started_at, completed_at = excluded.completed_at, "
            "attempt = excluded.attempt "
            "WHERE step_key IS NOT excluded.step_key OR agent IS NOT excluded.agent "
            "OR status IS NOT excluded.status OR started_at IS NOT excluded.started_at "
            "OR completed_at IS NOT excluded.completed_at OR attempt IS NOT excluded.attempt",
            prepare_step_batch(run_id, steps),
        )

    def replace_run_steps_for_import(
        self, run_id: str, steps: list[dict[str, Any]], tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        """Discard a run's stored steps and write *steps* in their place (E44-S5).

        The full-replace path, kept for import and recovery flows that restore
        a run's steps wholesale. Normal execution checkpoints go through
        :meth:`update_run`, which persists incrementally.

        Args:
            run_id: Run whose steps are being replaced.
            steps: The complete ordered step list to store.
            tenant_id: Tenant the run must belong to.
        """
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            owned = conn.execute(
                f"SELECT 1 FROM runs WHERE id = ? {clause}", (run_id, *params)
            ).fetchone()
            if owned is None:
                return
            conn.execute("DELETE FROM run_steps WHERE run_id = ?", (run_id,))
            self._persist_run_steps(conn, run_id, steps)
            conn.commit()


__all__ = ["_RunsMixin"]
