"""SQLite MessageRepository implementation."""

from __future__ import annotations

from typing import Any, Iterable

from backend.persistence.sqlite_adapter._shared import _ConnectionOwner
from backend.persistence.tenancy import DEFAULT_TENANT_ID, sqlite_tenant_clause


class _MessagesMixin(_ConnectionOwner):
    """``messages`` table read/write, scoped per-tenant via a hand-written WHERE clause."""

    def list_messages(
        self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List all messages for a session scoped to *tenant_id*, in sequence order."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM messages WHERE session_id = ? {clause} ORDER BY sequence ASC",
                (session_id, *params),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_messages(
        self,
        session_id: str,
        run_id: str,
        messages: Iterable[dict[str, str]],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Append *messages* to a session's conversation (E44-S4).

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
            sqlite3.IntegrityError: If a concurrent append already claimed one
                of the allocated sequence numbers.
        """
        new_messages = list(messages)
        if not new_messages:
            return
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT MAX(sequence) FROM messages WHERE session_id = ? {clause}",
                (session_id, *params),
            ).fetchone()
            start = 0 if row is None or row[0] is None else int(row[0]) + 1
            conn.executemany(
                "INSERT INTO messages (session_id, run_id, sequence, role, content, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (session_id, run_id, offset, item["role"], item["content"], tenant_id)
                    for offset, item in enumerate(new_messages, start=start)
                ],
            )
            conn.commit()


__all__ = ["_MessagesMixin"]
