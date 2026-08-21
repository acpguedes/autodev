"""Postgres MessageRepository implementation."""

from __future__ import annotations

from typing import Any, Iterable

from backend.persistence.postgres_adapter._shared import _ConnectionOwner
from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant


class _MessagesMixin(_ConnectionOwner):
    """``messages`` table read/write, scoped per-tenant via Row-Level Security."""

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


__all__ = ["_MessagesMixin"]
