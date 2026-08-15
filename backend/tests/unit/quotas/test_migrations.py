"""Tests for the tenant-isolation health check (E11-S3 Task 2)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.quotas.migrations import (
    check_postgres_tenant_isolation,
    check_sqlite_tenant_isolation,
)


def test_sqlite_check_reports_tables_missing_tenant_id(tmp_path: Path) -> None:
    """A table without a tenant_id column is flagged."""
    db_path = tmp_path / "check.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, tenant_id TEXT)")
    conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY)")
    conn.commit()

    missing = check_sqlite_tenant_isolation(conn, tables=("sessions", "runs"))

    assert missing == ["runs"]


def test_sqlite_check_reports_nothing_missing_when_healthy(tmp_path: Path) -> None:
    """A fully tenant-scoped set of tables reports no gaps."""
    db_path = tmp_path / "check.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, tenant_id TEXT)")
    conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, tenant_id TEXT)")
    conn.commit()

    missing = check_sqlite_tenant_isolation(conn, tables=("sessions", "runs"))

    assert missing == []


def test_sqlite_check_treats_a_missing_table_as_missing_isolation(
    tmp_path: Path,
) -> None:
    """A table that does not exist at all is reported as missing isolation."""
    db_path = tmp_path / "check.db"
    conn = sqlite3.connect(str(db_path))

    missing = check_sqlite_tenant_isolation(conn, tables=("sessions",))

    assert missing == ["sessions"]


class _FakeCursor:
    """Minimal stand-in for a psycopg cursor over canned rows."""

    def __init__(self, rows: dict[str, tuple[bool, bool] | None]) -> None:
        self._rows = rows
        self._last: tuple[bool, bool] | None = None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> "_FakeCursor":
        table = params[0] if params else None
        self._last = self._rows.get(str(table))
        return self

    def fetchone(self) -> tuple[bool, bool] | None:
        return self._last


def test_postgres_check_reports_tables_missing_forced_rls() -> None:
    """A table without both ENABLE and FORCE row-level security is flagged."""
    conn = _FakeCursor(
        {
            "sessions": (True, True),
            "runs": (True, False),  # enabled but not forced
            "plugins": None,  # table not found
        }
    )

    missing = check_postgres_tenant_isolation(
        conn, tables=("sessions", "runs", "plugins")
    )

    assert missing == ["runs", "plugins"]


def test_postgres_check_reports_nothing_missing_when_healthy() -> None:
    """Every table with forced RLS reports no gaps."""
    conn = _FakeCursor({"sessions": (True, True), "runs": (True, True)})

    missing = check_postgres_tenant_isolation(conn, tables=("sessions", "runs"))

    assert missing == []
