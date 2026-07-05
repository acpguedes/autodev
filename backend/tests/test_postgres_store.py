"""Tests for the PostgreSQL state-store adapter."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from backend.persistence.postgres_adapter import PostgresPlanStore, PostgresStore


class FakeCursor:
    """In-memory stand-in for a psycopg cursor, recording executed SQL on its connection."""

    def __init__(self, conn: "FakeConnection") -> None:
        """Wrap the owning fake connection to record executed statements on."""
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        """Support use as a context manager, mirroring the real cursor API."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """No-op exit, present for context-manager parity with the real cursor."""
        return None

    def execute(self, sql: str, params: object = None) -> "FakeCursor":
        """Record the executed SQL and params on the owning connection."""
        self.conn.executed.append((sql, params))
        return self

    def fetchone(self) -> object:
        """Return ``None``, as no query results are simulated."""
        return None

    def fetchall(self) -> list[object]:
        """Return an empty list, as no query results are simulated."""
        return []


class FakeConnection:
    """In-memory stand-in for a psycopg connection, used to assert on executed migrations."""

    def __init__(self) -> None:
        """Initialize an empty executed-statement log and commit counter."""
        self.executed: list[tuple[str, object]] = []
        self.commits = 0

    def __enter__(self) -> "FakeConnection":
        """Support use as a context manager, mirroring the real connection API."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """No-op exit, present for context-manager parity with the real connection."""
        return None

    def cursor(self) -> FakeCursor:
        """Return a new fake cursor bound to this connection."""
        return FakeCursor(self)

    def execute(self, sql: str, params: object = None) -> FakeCursor:
        """Execute SQL via a fresh cursor, recording it on this connection."""
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self) -> None:
        """Increment the commit counter."""
        self.commits += 1


def install_fake_psycopg(monkeypatch: pytest.MonkeyPatch) -> list[FakeConnection]:
    """Patch ``sys.modules['psycopg']`` with a fake module recording connections made.

    Args:
        monkeypatch: Pytest fixture used to patch ``sys.modules``.

    Returns:
        The list of fake connections created via ``psycopg.connect``, appended
        to as the code under test connects.
    """
    connections: list[FakeConnection] = []

    def connect(database_url: str) -> FakeConnection:
        """Create and record a fake connection for the given (assumed PostgreSQL) URL."""
        assert database_url.startswith("postgresql://")
        conn = FakeConnection()
        connections.append(conn)
        return conn

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    return connections


def test_postgres_store_runs_core_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing a :class:`PostgresStore` runs its core table migrations."""
    connections = install_fake_psycopg(monkeypatch)

    PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    executed_sql = "\n".join(sql for sql, _params in connections[0].executed)
    assert "CREATE TABLE IF NOT EXISTS sessions" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS runs" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS run_steps" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS messages" in executed_sql


def test_postgres_plan_store_runs_plan_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing a :class:`PostgresPlanStore` runs its plan table migrations."""
    connections = install_fake_psycopg(monkeypatch)

    PostgresPlanStore(database_url="postgresql://autodev:autodev@postgres/autodev")

    executed_sql = "\n".join(sql for sql, _params in connections[0].executed)
    assert "CREATE TABLE IF NOT EXISTS plan_documents" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS plan_approvals" in executed_sql
