"""Postgres SessionRepository implementation."""

from __future__ import annotations

from typing import Any

import psycopg

from backend.persistence.codecs import build_session_record, dumps_json, loads_json
from backend.persistence.contract import translate_integrity_error
from backend.persistence.postgres_adapter._shared import _ConnectionOwner
from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant


class _SessionsMixin(_ConnectionOwner):
    """``sessions`` table read/write, scoped per-tenant via Row-Level Security."""

    def create_session(
        self,
        *,
        session_id: str,
        goal: str,
        plan: list[str],
        artifacts: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Insert a new session row, scoped to *tenant_id*.

        Raises:
            backend.persistence.contract.PersistenceIntegrityError: If
                ``session_id`` already exists (E56-S2-T3: the same shared
                type SQLite raises for the same violation).
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            try:
                conn.execute(
                    "INSERT INTO sessions (id, goal, plan_json, artifacts_json, tenant_id) "
                    "VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)",
                    (session_id, goal, dumps_json(plan), dumps_json(artifacts), tenant_id),
                )
            except psycopg.errors.IntegrityError as exc:
                conn.rollback()
                raise translate_integrity_error(exc) from exc
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
        return build_session_record(
            id=row[0],
            goal=row[1],
            plan=loads_json(row[2]),
            artifacts=loads_json(row[3]),
            created_at=str(row[4]),
            updated_at=str(row[5]),
        )

    def list_sessions(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List all sessions visible to *tenant_id*, most recently created first."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                "SELECT id, goal, plan_json, artifacts_json, created_at, updated_at FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [
            build_session_record(
                id=row[0],
                goal=row[1],
                plan=loads_json(row[2]),
                artifacts=loads_json(row[3]),
                created_at=str(row[4]),
                updated_at=str(row[5]),
            )
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
            record = build_session_record(
                id=row[0],
                goal=row[1],
                plan=loads_json(row[2]),
                artifacts=loads_json(row[3]),
                created_at=str(row[4]),
                updated_at=str(row[5]),
            )
            record["message_count"] = count
            record["last_activity"] = last_activity
            page.append(record)
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
                (dumps_json(artifacts), session_id),
            )
            conn.commit()


__all__ = ["_SessionsMixin"]
