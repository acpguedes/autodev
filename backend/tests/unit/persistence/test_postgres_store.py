"""Tests for the PostgreSQL state-store adapter."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from backend.persistence.postgres_adapter import PostgresPlanStore, PostgresStore
from backend.persistence.postgres_adapter.vector_provisioning import VectorExtensionUnavailable


class FakeCursor:
    """In-memory stand-in for a psycopg cursor, recording executed SQL on its connection."""

    def __init__(self, conn: "FakeConnection") -> None:
        """Wrap the owning fake connection to record executed statements on."""
        self.conn = conn
        self._last_sql = ""

    def __enter__(self) -> "FakeCursor":
        """Support use as a context manager, mirroring the real cursor API."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """No-op exit, present for context-manager parity with the real cursor."""
        return None

    def execute(self, sql: str, params: object = None) -> "FakeCursor":
        """Record the executed SQL and params on the owning connection.

        Raises the connection's configured ``create_extension_error`` when
        *sql* is a ``CREATE EXTENSION`` statement, simulating a role without
        the privilege to create extensions.
        """
        self.conn.executed.append((sql, params))
        self._last_sql = sql
        if "CREATE EXTENSION" in sql and self.conn.create_extension_error is not None:
            raise self.conn.create_extension_error
        return self

    def fetchone(self) -> object:
        """Return a truthy row for a ``pg_extension`` presence check when configured, else ``None``."""
        if "pg_extension" in self._last_sql and self.conn.pg_extension_installed:
            return (1,)
        return None

    def fetchall(self) -> list[object]:
        """Return an empty list, as no query results are simulated."""
        return []


class FakeConnection:
    """In-memory stand-in for a psycopg connection, used to assert on executed migrations."""

    def __init__(
        self,
        pg_extension_installed: bool = False,
        create_extension_error: Exception | None = None,
    ) -> None:
        """Initialize an empty executed-statement log and commit counter.

        Args:
            pg_extension_installed: Whether ``SELECT ... FROM pg_extension``
                should report the ``vector`` extension as already installed.
            create_extension_error: If set, raised when ``CREATE EXTENSION``
                is executed, simulating a role without that privilege.
        """
        self.executed: list[tuple[str, object]] = []
        self.commits = 0
        self.pg_extension_installed = pg_extension_installed
        self.create_extension_error = create_extension_error

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


def install_fake_psycopg(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pg_extension_installed: bool = False,
    create_extension_error: Exception | None = None,
) -> list[FakeConnection]:
    """Patch ``sys.modules['psycopg']`` with a fake module recording connections made.

    Args:
        monkeypatch: Pytest fixture used to patch ``sys.modules``.
        pg_extension_installed: Forwarded to each created :class:`FakeConnection`.
        create_extension_error: Forwarded to each created :class:`FakeConnection`.

    Returns:
        The list of fake connections created via ``psycopg.connect``, appended
        to as the code under test connects.
    """
    connections: list[FakeConnection] = []

    def connect(database_url: str) -> FakeConnection:
        """Create and record a fake connection for the given (assumed PostgreSQL) URL."""
        assert database_url.startswith("postgresql://")
        conn = FakeConnection(
            pg_extension_installed=pg_extension_installed,
            create_extension_error=create_extension_error,
        )
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


def test_provision_vector_extension_creates_when_absent_and_creatable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``vector`` is absent and creatable, construction creates it (E48-S2)."""
    connections = install_fake_psycopg(
        monkeypatch, pg_extension_installed=False, create_extension_error=None
    )

    PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    executed_sql = "\n".join(sql for sql, _params in connections[0].executed)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in executed_sql


def test_provision_vector_extension_raises_when_absent_and_not_creatable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``vector`` is absent and this role lacks the privilege, construction fails
    closed with an actionable error and no migration is applied (E48-S2)."""
    connections = install_fake_psycopg(
        monkeypatch,
        pg_extension_installed=False,
        create_extension_error=RuntimeError("permission denied to create extension"),
    )

    with pytest.raises(VectorExtensionUnavailable, match="CREATE EXTENSION vector"):
        PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    executed_sql = "\n".join(sql for sql, _params in connections[0].executed)
    assert "CREATE TABLE IF NOT EXISTS sessions" not in executed_sql


def test_provision_vector_extension_skips_create_when_already_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``vector`` is already installed, construction never attempts
    ``CREATE EXTENSION`` at all — proving a role without that privilege still
    boots successfully (E48-S2)."""
    connections = install_fake_psycopg(monkeypatch, pg_extension_installed=True)

    PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    executed_sql = "\n".join(sql for sql, _params in connections[0].executed)
    assert "CREATE EXTENSION" not in executed_sql
    assert "CREATE TABLE IF NOT EXISTS sessions" in executed_sql
