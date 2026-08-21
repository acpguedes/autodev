"""Postgres RunRepository implementation."""

from __future__ import annotations

from typing import Any

from backend.persistence.codecs import (
    build_run_record,
    build_step_record,
    dumps_json,
    group_steps_by_run,
    loads_json,
    prepare_step_batch,
)
from backend.persistence.postgres_adapter._shared import _ConnectionOwner
from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant


class _RunsMixin(_ConnectionOwner):
    """``runs`` and ``run_steps`` table read/write, scoped per-tenant via Row-Level Security."""

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
        """Insert a new run row along with its steps, scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                """
                INSERT INTO runs (id, session_id, status, run_type, current_state, trigger_message, results_json, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (run_id, session_id, status, run_type, current_state, trigger_message, dumps_json(results), tenant_id),
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
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                """
                UPDATE runs
                SET status = %s, current_state = %s, results_json = %s::jsonb, completed_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (status, current_state, dumps_json(results), run_id),
            )
            self._persist_run_steps(conn, run_id, steps)
            conn.commit()

    def list_runs(self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List all runs for a session visible to *tenant_id*, most recently created first."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                """
                SELECT id, session_id, status, run_type, current_state, trigger_message,
                       results_json, created_at, completed_at
                FROM runs WHERE session_id = %s ORDER BY created_at DESC
                """,
                (session_id,),
            ).fetchall()
            steps_by_run = self._fetch_steps_for_runs(conn, [row[0] for row in rows])
        return [self._decode_run(row, steps_by_run.get(row[0], [])) for row in rows]

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
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM runs WHERE session_id = %s", (session_id,)
                ).fetchone()[0]
            )
            rows = conn.execute(
                """
                SELECT id, session_id, status, run_type, current_state, trigger_message,
                       results_json, created_at, completed_at
                FROM runs WHERE session_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s
                """,
                (session_id, limit, offset),
            ).fetchall()
            steps_by_run = self._fetch_steps_for_runs(conn, [row[0] for row in rows])
        return [self._decode_run(row, steps_by_run.get(row[0], [])) for row in rows], total

    def get_run(self, run_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any] | None:
        """Fetch a single run by its primary key, visible to *tenant_id* (E44-S1).

        The session-agnostic counterpart to :meth:`list_runs`: it resolves a
        run without knowing which session owns it, so callers holding only a
        run id (e.g. ``GET /v2/turns/{turn_id}``) no longer have to scan every
        session's runs. Costs exactly two statements on one connection — the
        indexed primary-key lookup plus one batched step query. RLS on
        ``runs`` already hides other tenants' rows; the explicit
        ``set_postgres_tenant`` call is what arms it.

        Args:
            run_id: Identifier of the run to fetch.
            tenant_id: Tenant the run must belong to; a run owned by another
                tenant is indistinguishable from a nonexistent one.

        Returns:
            The decoded run record, or ``None`` when no run with that id is
            visible to *tenant_id*.
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                """
                SELECT id, session_id, status, run_type, current_state, trigger_message,
                       results_json, created_at, completed_at
                FROM runs WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            steps = self._fetch_steps_for_runs(conn, [run_id]).get(run_id, [])
        return self._decode_run(row, steps)

    @staticmethod
    def _decode_run(row: Any, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Decode one ``runs`` row into the store's public dict shape.

        Pure by design (E44-S1): steps are passed in already fetched, so
        decoding never issues a query — and never opens a connection — of its
        own.

        Args:
            row: The raw ``runs`` row, in this module's fixed column order.
            steps: The run's already-fetched step records, in execution order.

        Returns:
            The decoded run record.
        """
        return build_run_record(
            id=row[0],
            session_id=row[1],
            status=row[2],
            run_type=row[3],
            current_state=row[4],
            trigger_message=row[5],
            results=loads_json(row[6]),
            steps=steps,
            created_at=str(row[7]),
            completed_at=str(row[8]),
        )

    @staticmethod
    def _fetch_steps_for_runs(conn: Any, run_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Load every step of *run_ids* in one query, grouped by run id (E44-S1).

        ``run_steps`` has no ``tenant_id`` column or RLS policy of its own
        (ADR-010); the ``JOIN`` against ``runs`` is what applies the parent's
        RLS predicate, so steps of another tenant's run never surface here
        even when its id is passed in explicitly.

        Args:
            conn: An open, already tenant-scoped connection to reuse; no new
                connection is opened.
            run_ids: Run identifiers whose steps should be loaded.

        Returns:
            A mapping of run id to its steps in execution order. Runs with no
            steps are absent from the mapping.
        """
        if not run_ids:
            return {}
        rows = conn.execute(
            """
            SELECT rs.run_id, rs.step_key, rs.agent, rs.status, rs.started_at, rs.completed_at,
                   rs.attempt
            FROM run_steps rs
            JOIN runs r ON r.id = rs.run_id
            WHERE rs.run_id = ANY(%s)
            ORDER BY rs.run_id, rs.position ASC, rs.id ASC
            """,
            (list(run_ids),),
        ).fetchall()
        return group_steps_by_run(
            (
                row[0],
                build_step_record(
                    step_key=row[1],
                    agent=row[2],
                    status=row[3],
                    started_at=row[4],
                    completed_at=row[5],
                    attempt=row[6],
                ),
            )
            for row in rows
        )

    def list_run_steps(self, run_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List all steps recorded for a run, in execution order, scoped to *tenant_id*.

        ``run_steps`` has no ``tenant_id`` column or RLS policy of its own —
        by design (ADR-010), it is scoped transitively through its parent
        ``runs`` row. The ``JOIN`` below is what makes that transitive
        scoping actually take effect: RLS on ``runs`` hides any row outside
        *tenant_id*'s scope, so a ``run_id`` belonging to another tenant
        yields zero joined rows here, even though ``run_steps`` itself has
        no filter of its own.
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                """
                SELECT rs.step_key, rs.agent, rs.status, rs.started_at, rs.completed_at, rs.attempt
                FROM run_steps rs
                JOIN runs r ON r.id = rs.run_id
                WHERE rs.run_id = %s
                ORDER BY rs.position ASC, rs.id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            build_step_record(
                step_key=row[0],
                agent=row[1],
                status=row[2],
                started_at=row[3],
                completed_at=row[4],
                attempt=row[5],
            )
            for row in rows
        ]

    @staticmethod
    def _persist_run_steps(conn: Any, run_id: str, steps: list[dict[str, Any]]) -> None:
        """Persist a run's ordered step list incrementally (E44-S5).

        Upserts each step onto its ``(run_id, position)`` key in one batched
        statement (E44-S2) and suppresses the ``DO UPDATE`` when nothing about
        the row changed, so a checkpoint that adds the Nth step writes one row
        rather than deleting and re-inserting all N. Trailing rows beyond the
        current list length are trimmed, which is what makes a shortened list
        (e.g. a resumed run dropping its ``awaiting_approval`` placeholder)
        converge.

        Args:
            conn: An open, already tenant-scoped connection inside the
                caller's transaction.
            run_id: Run whose steps are being persisted.
            steps: The run's full ordered step list.
        """
        conn.execute(
            "DELETE FROM run_steps WHERE run_id = %s AND position >= %s", (run_id, len(steps))
        )
        if not steps:
            return
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO run_steps
                    (run_id, position, step_key, agent, status, started_at, completed_at, attempt)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, position) DO UPDATE SET
                    step_key = EXCLUDED.step_key,
                    agent = EXCLUDED.agent,
                    status = EXCLUDED.status,
                    started_at = EXCLUDED.started_at,
                    completed_at = EXCLUDED.completed_at,
                    attempt = EXCLUDED.attempt
                WHERE (run_steps.step_key, run_steps.agent, run_steps.status, run_steps.started_at,
                       run_steps.completed_at, run_steps.attempt)
                      IS DISTINCT FROM
                      (EXCLUDED.step_key, EXCLUDED.agent, EXCLUDED.status, EXCLUDED.started_at,
                       EXCLUDED.completed_at, EXCLUDED.attempt)
                """,
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
            tenant_id: Tenant the run must belong to; RLS on ``runs`` makes a
                run outside its scope a no-op.
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            owned = conn.execute("SELECT 1 FROM runs WHERE id = %s", (run_id,)).fetchone()
            if owned is None:
                return
            conn.execute("DELETE FROM run_steps WHERE run_id = %s", (run_id,))
            self._persist_run_steps(conn, run_id, steps)
            conn.commit()


__all__ = ["_RunsMixin"]
