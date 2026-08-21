"""SQLite SessionRepository implementation."""

from __future__ import annotations

import sqlite3
from typing import Any

from backend.persistence.codecs import build_session_record, dumps_json, loads_json
from backend.persistence.sqlite_adapter._shared import _ConnectionOwner
from backend.persistence.tenancy import DEFAULT_TENANT_ID, sqlite_tenant_clause


class _SessionsMixin(_ConnectionOwner):
    """``sessions`` table read/write, scoped per-tenant via a hand-written WHERE clause.

    See :class:`backend.persistence.sqlite_adapter.store.SQLiteStore` for the
    tenancy rationale shared across every mixin in this package.
    """

    def create_session(
        self,
        *,
        session_id: str,
        goal: str,
        plan: list[str],
        artifacts: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Insert a new session row scoped to *tenant_id*.

        Args:
            session_id: Unique identifier for the session.
            goal: The session's stated goal.
            plan: Ordered list of plan step descriptions.
            artifacts: Arbitrary session artifacts, serialized to JSON.
            tenant_id: Tenant the new session belongs to.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, goal, plan_json, artifacts_json, tenant_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, goal, dumps_json(plan), dumps_json(artifacts), tenant_id),
            )
            conn.commit()

    def get_session(
        self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, Any] | None:
        """Fetch a session by id scoped to *tenant_id*, or ``None`` if not found."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT * FROM sessions WHERE id = ? {clause}", (session_id, *params)
            ).fetchone()
        return self._decode_session(row)

    def list_sessions(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List all sessions for *tenant_id*, most recently created first."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM sessions WHERE 1=1 {clause} ORDER BY created_at DESC", params
            ).fetchall()
        return [self._decode_session(row) for row in rows]  # type: ignore[misc]

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
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM sessions WHERE 1=1 {clause}", params
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"SELECT * FROM sessions WHERE 1=1 {clause} ORDER BY created_at DESC "
                f"LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            activity = self._fetch_message_activity(
                conn, [row["id"] for row in rows], tenant_id
            )
        page: list[dict[str, Any]] = []
        for row in rows:
            record = self._decode_session(row)
            assert record is not None  # rows from a SELECT are never None
            count, last_activity = activity.get(record["id"], (0, None))
            record["message_count"] = count
            record["last_activity"] = last_activity
            page.append(record)
        return page, total

    @staticmethod
    def _fetch_message_activity(
        conn: sqlite3.Connection, session_ids: list[str], tenant_id: str
    ) -> dict[str, tuple[int, str | None]]:
        """Aggregate message count and last activity for *session_ids* in one query.

        Args:
            conn: An open connection to reuse; no new connection is opened.
            session_ids: Sessions to summarize.
            tenant_id: Tenant the messages must belong to.

        Returns:
            A mapping of session id to ``(message_count, last_activity)``.
            Sessions with no messages are absent from the mapping.
        """
        if not session_ids:
            return {}
        placeholders = ", ".join("?" for _ in session_ids)
        rows = conn.execute(
            "SELECT session_id, COUNT(*) AS message_count, MAX(created_at) AS last_activity "
            f"FROM messages WHERE session_id IN ({placeholders}) AND tenant_id = ? "
            "GROUP BY session_id",
            (*session_ids, tenant_id),
        ).fetchall()
        return {row["session_id"]: (int(row["message_count"]), row["last_activity"]) for row in rows}

    def update_session_artifacts(
        self,
        session_id: str,
        artifacts: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Replace a session's stored artifacts, scoped to *tenant_id*."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE sessions SET artifacts_json = ?, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id = ? {clause}",
                (dumps_json(artifacts), session_id, *params),
            )
            conn.commit()

    def _decode_session(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return build_session_record(
            id=row["id"],
            goal=row["goal"],
            plan=loads_json(row["plan_json"]),
            artifacts=loads_json(row["artifacts_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


__all__ = ["_SessionsMixin"]
