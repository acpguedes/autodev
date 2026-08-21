"""PostgreSQL implementations of the persistence repository protocols."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.postgres_versions import (
    POSTGRES_STORE_MIGRATIONS,
    add_tenant_id_and_rls_to_plan_tables,
)
from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant
from backend.plans.models import ApprovalRecord, PlanDocument, PlanStatus

_DEFAULT_DATABASE_URL = "postgresql://autodev:autodev@postgres:5432/autodev"


def _connect(database_url: str) -> Any:
    """Open a new psycopg connection to the given PostgreSQL URL.

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        A new database connection.

    Raises:
        RuntimeError: If the ``psycopg`` package is not installed.
    """
    try:
        import psycopg  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError(
            "psycopg is required for PostgreSQL persistence. Install backend requirements."
        ) from exc
    return psycopg.connect(database_url)

def _json(value: Any) -> str:
    """Serialize a value to a JSON string."""
    return json.dumps(value)

def _loads(value: Any) -> Any:
    """Deserialize a JSON string, passing non-string values through unchanged."""
    if isinstance(value, str):
        return json.loads(value)
    return value

def _run_sql(conn: Any, statements: Iterable[str]) -> None:
    """Execute and commit a sequence of SQL statements on one connection."""
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()

class PostgresStore:
    """Postgres-backed store implementing sessions, runs, and messages."""

    def __init__(self, database_url: str = _DEFAULT_DATABASE_URL) -> None:
        """Initialize the store and apply its migrations.

        Args:
            database_url: PostgreSQL connection URL.
        """
        self.database_url = database_url
        with self.connect() as conn:
            self._run_migrations(conn)

    def connect(self) -> Any:
        """Open a new connection to this store's database."""
        return _connect(self.database_url)

    def _run_migrations(self, conn: Any) -> None:
        """Apply this store's versioned migrations via the shared runner.

        Uses the same :class:`MigrationRunner` machinery as
        :class:`~backend.persistence.sqlite_adapter.SQLiteStore`, running
        against a psycopg connection (``engine="postgres"``) instead of ad
        hoc ``CREATE TABLE IF NOT EXISTS`` statements. See
        ``backend/persistence/migrations/postgres_versions.py`` for the
        migration list.
        """
        MigrationRunner(
            conn, POSTGRES_STORE_MIGRATIONS, namespace="store", engine="postgres"
        ).run_pending()

    def create_session(
        self,
        *,
        session_id: str,
        goal: str,
        plan: list[str],
        artifacts: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Insert a new session row, scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                "INSERT INTO sessions (id, goal, plan_json, artifacts_json, tenant_id) "
                "VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)",
                (session_id, goal, _json(plan), _json(artifacts), tenant_id),
            )
            conn.commit()

    def get_session(self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any] | None:
        """Fetch a session by id, or ``None`` if it does not exist or is outside *tenant_id*'s scope."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                "SELECT id, goal, plan_json, artifacts_json, created_at, updated_at FROM sessions WHERE id = %s",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "goal": row[1],
            "plan": _loads(row[2]),
            "artifacts": _loads(row[3]),
            "created_at": str(row[4]),
            "updated_at": str(row[5]),
        }

    def list_sessions(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List all sessions visible to *tenant_id*, most recently created first."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                "SELECT id, goal, plan_json, artifacts_json, created_at, updated_at FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": row[0],
                "goal": row[1],
                "plan": _loads(row[2]),
                "artifacts": _loads(row[3]),
                "created_at": str(row[4]),
                "updated_at": str(row[5]),
            }
            for row in rows
        ]

    def list_sessions_page(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of sessions plus the tenant's total session count (E44-S3).

        Paginates in SQL (``LIMIT``/``OFFSET``) rather than loading every row
        and slicing in the API layer, and derives each session's activity
        summary from one aggregate over the page's sessions instead of
        replaying every session's message history.

        Args:
            limit: Maximum number of sessions to return.
            offset: Number of sessions to skip, in listing order.
            tenant_id: Tenant to scope the listing to.

        Returns:
            A ``(page, total)`` pair. Each page record has the same shape
            :meth:`get_session` returns, plus ``message_count`` and
            ``last_activity`` (``None`` when the session has no messages).
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            total = int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
            rows = conn.execute(
                """
                SELECT id, goal, plan_json, artifacts_json, created_at, updated_at
                FROM sessions ORDER BY created_at DESC LIMIT %s OFFSET %s
                """,
                (limit, offset),
            ).fetchall()
            activity = self._fetch_message_activity(conn, [row[0] for row in rows])
        page: list[dict[str, Any]] = []
        for row in rows:
            count, last_activity = activity.get(row[0], (0, None))
            page.append(
                {
                    "id": row[0],
                    "goal": row[1],
                    "plan": _loads(row[2]),
                    "artifacts": _loads(row[3]),
                    "created_at": str(row[4]),
                    "updated_at": str(row[5]),
                    "message_count": count,
                    "last_activity": last_activity,
                }
            )
        return page, total

    @staticmethod
    def _fetch_message_activity(
        conn: Any, session_ids: list[str]
    ) -> dict[str, tuple[int, str | None]]:
        """Aggregate message count and last activity for *session_ids* in one query.

        RLS on ``messages`` already restricts the aggregate to the connection's
        tenant, so no explicit tenant predicate is repeated here.

        Args:
            conn: An open, already tenant-scoped connection to reuse; no new
                connection is opened.
            session_ids: Sessions to summarize.

        Returns:
            A mapping of session id to ``(message_count, last_activity)``.
            Sessions with no messages are absent from the mapping.
        """
        if not session_ids:
            return {}
        rows = conn.execute(
            """
            SELECT session_id, COUNT(*), MAX(created_at)
            FROM messages WHERE session_id = ANY(%s) GROUP BY session_id
            """,
            (list(session_ids),),
        ).fetchall()
        return {row[0]: (int(row[1]), None if row[2] is None else str(row[2])) for row in rows}

    def update_session_artifacts(
        self, session_id: str, artifacts: dict[str, Any], tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        """Replace a session's stored artifacts, scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                "UPDATE sessions SET artifacts_json = %s::jsonb, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (_json(artifacts), session_id),
            )
            conn.commit()

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
                (run_id, session_id, status, run_type, current_state, trigger_message, _json(results), tenant_id),
            )
            self._replace_run_steps(conn, run_id, steps)
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
                (status, current_state, _json(results), run_id),
            )
            self._replace_run_steps(conn, run_id, steps)
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
        return {
            "id": row[0],
            "session_id": row[1],
            "status": row[2],
            "run_type": row[3],
            "current_state": row[4],
            "trigger_message": row[5],
            "results": _loads(row[6]),
            "steps": steps,
            "created_at": str(row[7]),
            "completed_at": str(row[8]),
        }

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
            ORDER BY rs.id ASC
            """,
            (list(run_ids),),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row[0], []).append(
                {
                    "step_key": row[1],
                    "agent": row[2],
                    "status": row[3],
                    "started_at": row[4],
                    "completed_at": row[5],
                    "attempt": row[6],
                }
            )
        return grouped

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
                ORDER BY rs.id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "step_key": row[0],
                "agent": row[1],
                "status": row[2],
                "started_at": row[3],
                "completed_at": row[4],
                "attempt": row[5],
            }
            for row in rows
        ]

    def list_messages(self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List all messages for a session visible to *tenant_id*, in sequence order."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                """
                SELECT id, session_id, run_id, sequence, role, content, created_at
                FROM messages WHERE session_id = %s ORDER BY sequence ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "session_id": row[1],
                "run_id": row[2],
                "sequence": row[3],
                "role": row[4],
                "content": row[5],
                "created_at": str(row[6]),
            }
            for row in rows
        ]

    def append_messages(
        self,
        session_id: str,
        run_id: str,
        messages: Iterable[dict[str, str]],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Append *messages* to a session's conversation, scoped to *tenant_id* (E44-S4).

        Takes only the new tail, not the full history: sequence numbers are
        allocated from ``MAX(sequence) + 1`` inside the same transaction as
        the insert, so an append reads one row regardless of how long the
        conversation is. The unique ``(tenant_id, session_id, sequence)``
        index makes concurrent appends fail closed rather than interleave
        into duplicate sequence numbers.

        Args:
            session_id: Identifier of the owning session.
            run_id: Identifier of the run that produced the messages.
            messages: The new messages to append, in order. Already-persisted
                messages must not be re-sent.
            tenant_id: Tenant the messages belong to.

        Raises:
            psycopg.errors.UniqueViolation: If a concurrent append already
                claimed one of the allocated sequence numbers.
        """
        new_messages = list(messages)
        if not new_messages:
            return
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                "SELECT MAX(sequence) FROM messages WHERE session_id = %s", (session_id,)
            ).fetchone()
            start = 0 if row is None or row[0] is None else int(row[0]) + 1
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO messages (session_id, run_id, sequence, role, content, tenant_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (session_id, run_id, offset, item["role"], item["content"], tenant_id)
                        for offset, item in enumerate(new_messages, start=start)
                    ],
                )
            conn.commit()

    def create_eval_result(
        self,
        *,
        eval_id: str,
        eval_version: str,
        run_id: str,
        document: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Persist one eval result document, scoped to *tenant_id*. Never overwrites an existing run (E5-S3)."""
        gate_passed = bool((document.get("gate") or {}).get("passed", True))
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                """
                INSERT INTO eval_results (eval_id, eval_version, run_id, mode, gate_passed, document_json, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    eval_id,
                    eval_version,
                    run_id,
                    str(document.get("mode", "offline")),
                    gate_passed,
                    _json(document),
                    tenant_id,
                ),
            )
            conn.commit()

    def get_eval_result(
        self, eval_id: str, eval_version: str, run_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, Any] | None:
        """Fetch one eval result document, or ``None`` if it does not exist (E5-S3), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                "SELECT document_json FROM eval_results WHERE eval_id = %s AND eval_version = %s AND run_id = %s",
                (eval_id, eval_version, run_id),
            ).fetchone()
        return _loads(row[0]) if row is not None else None

    def list_eval_results(
        self, eval_id: str, eval_version: str | None = None, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List eval result documents for an id, newest first, optionally by version (E5-S3), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            if eval_version is not None:
                rows = conn.execute(
                    "SELECT document_json FROM eval_results WHERE eval_id = %s AND eval_version = %s "
                    "ORDER BY id DESC",
                    (eval_id, eval_version),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT document_json FROM eval_results WHERE eval_id = %s ORDER BY id DESC",
                    (eval_id,),
                ).fetchall()
        return [_loads(row[0]) for row in rows]

    def create_score_snapshot(
        self,
        *,
        snapshot_id: str,
        sample_count: int,
        document: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Persist one immutable, versioned score snapshot document (E5-S4), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                "INSERT INTO score_snapshots (snapshot_id, sample_count, document_json, tenant_id) "
                "VALUES (%s, %s, %s::jsonb, %s)",
                (snapshot_id, sample_count, _json(document), tenant_id),
            )
            conn.commit()

    def get_score_snapshot(self, snapshot_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any] | None:
        """Fetch one persisted score snapshot document, or ``None`` (E5-S4), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                "SELECT document_json FROM score_snapshots WHERE snapshot_id = %s", (snapshot_id,)
            ).fetchone()
        return _loads(row[0]) if row is not None else None

    def list_score_snapshots(self, limit: int = 50, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List persisted score snapshots, newest first (E5-S4), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                "SELECT document_json FROM score_snapshots ORDER BY id DESC LIMIT %s", (limit,)
            ).fetchall()
        return [_loads(row[0]) for row in rows]

    def record_snapshot_promotion(
        self,
        *,
        policy_id: str,
        snapshot_id: str,
        baseline_snapshot_id: str,
        promoted: bool,
        reason: str,
        decided_at: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Append one promotion decision (promoted or blocked) to the audit log (E5-S4).

        ``score_snapshot_promotions`` has no ``tenant_id`` column or RLS
        policy of its own (ADR-010: scoped transitively through its parent
        ``score_snapshots`` row via *snapshot_id*), so this insert is not
        itself RLS-checked. *tenant_id* still scopes the transaction (via
        :func:`~backend.persistence.tenancy.set_postgres_tenant`) for
        consistency with every other method and any future reads sharing
        this connection.
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                "INSERT INTO score_snapshot_promotions "
                "(policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at),
            )
            conn.commit()

    def get_active_score_snapshot(self, policy_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any] | None:
        """Fetch the currently promoted snapshot document for a policy id (E5-S4), scoped to *tenant_id*.

        Joins to ``score_snapshots`` so RLS on that table (which does carry
        a ``tenant_id`` column and policy) transitively filters out
        promotions pointing at a snapshot outside *tenant_id*'s scope.
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                """
                SELECT ssp.snapshot_id
                FROM score_snapshot_promotions ssp
                JOIN score_snapshots ss ON ss.snapshot_id = ssp.snapshot_id
                WHERE ssp.policy_id = %s AND ssp.promoted = TRUE
                ORDER BY ssp.id DESC LIMIT 1
                """,
                (policy_id,),
            ).fetchone()
        if row is None:
            return None
        return self.get_score_snapshot(row[0], tenant_id=tenant_id)

    def list_snapshot_promotions(self, policy_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List every promotion decision recorded for a policy id, newest first (E5-S4), scoped to *tenant_id*.

        See :meth:`get_active_score_snapshot` for why this joins to
        ``score_snapshots``.
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                """
                SELECT ssp.policy_id, ssp.snapshot_id, ssp.baseline_snapshot_id, ssp.promoted, ssp.reason,
                       ssp.decided_at
                FROM score_snapshot_promotions ssp
                JOIN score_snapshots ss ON ss.snapshot_id = ssp.snapshot_id
                WHERE ssp.policy_id = %s ORDER BY ssp.id DESC
                """,
                (policy_id,),
            ).fetchall()
        return [
            {
                "policyId": row[0],
                "snapshotId": row[1],
                "baselineSnapshotId": row[2],
                "promoted": bool(row[3]),
                "reason": row[4],
                "decidedAt": row[5],
            }
            for row in rows
        ]

    def _replace_run_steps(self, conn: Any, run_id: str, steps: list[dict[str, Any]]) -> None:
        """Delete and re-insert all step rows for a run.

        Inserts go through a single ``executemany`` (E44-S2), matching what
        the SQLite adapter already did — one round trip for the whole step
        list instead of one per row.
        """
        conn.execute("DELETE FROM run_steps WHERE run_id = %s", (run_id,))
        if not steps:
            return
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO run_steps (run_id, step_key, agent, status, started_at, completed_at, attempt)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        run_id,
                        step["step_key"],
                        step["agent"],
                        step["status"],
                        step["started_at"],
                        step["completed_at"],
                        step.get("attempt", 1),
                    )
                    for step in steps
                ],
            )


class PostgresPlanStore:
    """Postgres-backed plan store."""

    def __init__(self, db_path: Optional[Path] = None, database_url: str = "") -> None:
        """Initialize the store and apply its migrations.

        Args:
            db_path: Unused; accepted for constructor-signature parity with
                the SQLite plan store.
            database_url: PostgreSQL connection URL; falls back to the
                ``DATABASE_URL`` env var.
        """
        del db_path
        self.database_url = database_url or os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
        with self.connect() as conn:
            self._run_migrations(conn)

    def connect(self) -> Any:
        """Open a new connection to this store's database."""
        return _connect(self.database_url)

    def _run_migrations(self, conn: Any) -> None:
        """Create the plan store's tables, apply tenancy DDL, and record the schema version.

        Calls :func:`add_tenant_id_and_rls_to_plan_tables` directly (rather
        than only relying on it running as a step in
        :data:`~backend.persistence.migrations.postgres_versions.POSTGRES_STORE_MIGRATIONS`)
        so this store is correctly tenant-scoped on its own, even if a
        :class:`PostgresStore` is never constructed against the same
        database (see that function's docstring for the full rationale).
        """
        _run_sql(
            conn,
            [
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    namespace TEXT PRIMARY KEY,
                    version INTEGER NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS plan_documents (
                    session_id TEXT PRIMARY KEY,
                    steps_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    status TEXT NOT NULL DEFAULT 'draft',
                    updated_at TEXT NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS plan_approvals (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """,
                """
                INSERT INTO schema_version (namespace, version)
                VALUES ('plan_store', 1)
                ON CONFLICT(namespace) DO UPDATE SET version = EXCLUDED.version
                """,
            ],
        )
        add_tenant_id_and_rls_to_plan_tables(conn)
        conn.commit()

    def upsert_plan(self, session_id: str, steps: list[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Create or replace a session's plan document, resetting its status to draft, scoped to *tenant_id*."""
        now = self._now()
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                """
                INSERT INTO plan_documents (session_id, steps_json, status, updated_at, tenant_id)
                VALUES (%s, %s::jsonb, 'draft', %s, %s)
                ON CONFLICT(session_id) DO UPDATE SET
                    steps_json = EXCLUDED.steps_json,
                    status = 'draft',
                    updated_at = EXCLUDED.updated_at
                """,
                (session_id, _json(steps), now, tenant_id),
            )
            conn.commit()

    def get_plan(self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Optional[PlanDocument]:
        """Fetch a session's plan document, or ``None`` if it does not exist, scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                "SELECT session_id, steps_json, status, updated_at FROM plan_documents WHERE session_id = %s",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return PlanDocument(
            session_id=row[0],
            steps=_loads(row[1]),
            status=row[2],
            updated_at=row[3],
        )

    def set_status(self, session_id: str, status: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Update a session's plan status, scoped to *tenant_id*."""
        now = self._now()
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                "UPDATE plan_documents SET status = %s, updated_at = %s WHERE session_id = %s",
                (status, now, session_id),
            )
            conn.commit()

    def approve(self, session_id: str, actor: str, note: str = "", tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Mark a session's plan as approved and record the approval, scoped to *tenant_id*."""
        self.set_status(session_id, PlanStatus.APPROVED, tenant_id=tenant_id)
        self._append_approval(
            session_id, decision=PlanStatus.APPROVED, actor=actor, note=note, tenant_id=tenant_id
        )

    def reject(self, session_id: str, actor: str, note: str = "", tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Mark a session's plan as rejected and record the rejection, scoped to *tenant_id*."""
        self.set_status(session_id, PlanStatus.REJECTED, tenant_id=tenant_id)
        self._append_approval(
            session_id, decision=PlanStatus.REJECTED, actor=actor, note=note, tenant_id=tenant_id
        )

    def list_plans(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[PlanDocument]:
        """List all plan documents visible to *tenant_id*, most recently updated first."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                "SELECT session_id, steps_json, status, updated_at FROM plan_documents ORDER BY updated_at DESC"
            ).fetchall()
        return [
            PlanDocument(
                session_id=row[0],
                steps=_loads(row[1]),
                status=row[2],
                updated_at=row[3],
            )
            for row in rows
        ]

    def list_approvals(self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> list[ApprovalRecord]:
        """List all approval decisions for a session's plan, oldest first, scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                """
                SELECT session_id, decision, actor, note, created_at
                FROM plan_approvals WHERE session_id = %s ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            ApprovalRecord(
                session_id=row[0],
                decision=row[1],
                actor=row[2],
                note=row[3],
                created_at=row[4],
            )
            for row in rows
        ]

    def _append_approval(
        self, session_id: str, decision: str, actor: str, note: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        """Insert an approval decision record for a session, scoped to *tenant_id*."""
        now = self._now()
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                """
                INSERT INTO plan_approvals (session_id, decision, actor, note, created_at, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (session_id, decision, actor, note, now, tenant_id),
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        """Return the current UTC timestamp in ISO 8601 format."""
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

__all__ = ["PostgresPlanStore", "PostgresStore"]
