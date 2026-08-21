"""Statement- and write-counting helpers shared by the E44 cost regression tests."""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from backend.persistence.sqlite_adapter import SQLiteStore

from backend.tests.unit.persistence.test_postgres_adapter import ScriptedConnection

#: Statements SQLite emits for transaction control, which are not data access
#: and therefore excluded from the counts the E44 tests assert on.
_TRANSACTION_CONTROL = ("BEGIN", "COMMIT", "ROLLBACK")


class StatementCounter:
    """Record every data statement a :class:`SQLiteStore` executes."""

    def __init__(self) -> None:
        """Start with no recorded statements and no opened connections."""
        self.statements: list[str] = []
        self.connections = 0

    def install(self, target: SQLiteStore) -> None:
        """Wrap *target*'s ``connect`` so every statement it runs is recorded.

        Args:
            target: The store whose connections should be instrumented.
        """
        original = target.connect

        def counting_connect() -> sqlite3.Connection:
            conn = original()
            self.connections += 1
            conn.set_trace_callback(self._record)
            return conn

        target.connect = counting_connect  # type: ignore[method-assign]

    def _record(self, statement: str) -> None:
        """Record *statement* unless it is transaction control."""
        if not statement.strip().upper().startswith(_TRANSACTION_CONTROL):
            self.statements.append(statement)

    def reset(self) -> None:
        """Clear recorded statements and the connection count."""
        self.statements.clear()
        self.connections = 0


def data_statements(conn: ScriptedConnection) -> list[str]:
    """Return a scripted connection's statements minus tenant-scoping ``set_config`` calls.

    Args:
        conn: The scripted psycopg connection to read.

    Returns:
        The executed SQL statements that represent real data access.
    """
    return [sql for sql, _ in conn.executed if "set_config" not in sql]


def rows_written(target: SQLiteStore, action: Callable[[], Any]) -> int:
    """Return how many rows *action* actually inserted, updated, or deleted.

    ``sqlite3.Connection.total_changes`` counts real row writes, so an upsert
    whose ``DO UPDATE`` is suppressed by its ``WHERE`` clause contributes
    nothing — which is exactly what the E44-S5 tests measure.

    Args:
        target: The store whose connections should be measured.
        action: A zero-argument callable performing the writes.

    Returns:
        The total number of rows written across every connection opened.
    """
    original = target.connect
    opened: list[sqlite3.Connection] = []

    def counting_connect() -> sqlite3.Connection:
        conn = original()
        opened.append(conn)
        return conn

    target.connect = counting_connect  # type: ignore[method-assign]
    try:
        action()
    finally:
        target.connect = original  # type: ignore[method-assign]
    return sum(conn.total_changes for conn in opened)
