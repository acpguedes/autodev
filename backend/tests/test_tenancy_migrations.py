"""Tests for the E8-S1 scoped tenancy slice: down migrations and RLS DDL (ADR-010)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence, cast

import pytest

from backend.persistence.migrations.postgres_versions import POSTGRES_STORE_MIGRATIONS
from backend.persistence.migrations.runner import Migration, MigrationRunner
from backend.persistence.migrations.versions import STORE_MIGRATIONS
from backend.persistence.postgres_adapter import PostgresPlanStore, PostgresStore
from backend.persistence.tenancy import (
    DEFAULT_TENANT_ID,
    set_postgres_tenant,
    sqlite_tenant_clause,
)


class FakeCursor:
    """In-memory stand-in for a psycopg cursor, recording executed SQL on its connection."""

    def __init__(self, conn: "FakeConnection") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> "FakeCursor":
        self.conn.executed.append((sql, params))
        return self

    def fetchone(self) -> object:
        return None

    def fetchall(self) -> list[object]:
        return []


class FakeConnection:
    """In-memory stand-in for a psycopg connection, used to assert on executed DDL."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []
        self.commits = 0

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def execute(self, sql: str, params: object = None) -> FakeCursor:
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self) -> None:
        self.commits += 1


def install_fake_psycopg(monkeypatch: pytest.MonkeyPatch) -> list[FakeConnection]:
    """Patch ``sys.modules['psycopg']`` with a fake module recording connections made."""
    import sys
    from types import SimpleNamespace

    connections: list[FakeConnection] = []

    def connect(database_url: str) -> FakeConnection:
        assert database_url.startswith("postgresql://")
        conn = FakeConnection()
        connections.append(conn)
        return conn

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    return connections


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names currently defined on *table*."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------------------------------------------------------------------------
# SQLite: up -> down -> up round trip
# ---------------------------------------------------------------------------


def _migration_index(name: str) -> int:
    """Return the 1-based position of the migration named *name* in ``STORE_MIGRATIONS``.

    Looking this up by name (rather than hardcoding a step count) keeps the
    round-trip test below correct as later stories append more migrations
    after the tenancy one (e.g. E7-S1's ``code_chunks`` table).
    """
    for index, migration in enumerate(STORE_MIGRATIONS, start=1):
        if getattr(migration, "name", "") == name:
            return index
    raise AssertionError(f"no migration named {name!r} in STORE_MIGRATIONS")


def test_sqlite_migrations_up_down_up_roundtrip(tmp_path: Path) -> None:
    """Applying, rolling back (through the tenancy migration), and reapplying reaches the same schema."""
    db_path = tmp_path / "roundtrip.db"
    conn = sqlite3.connect(db_path)
    try:
        runner = MigrationRunner(conn, STORE_MIGRATIONS, namespace="store")
        runner.run_pending()
        assert "tenant_id" in _columns(conn, "sessions")
        assert "tenant_id" in _columns(conn, "runs")
        assert "tenant_id" in _columns(conn, "messages")

        tenant_migration_index = _migration_index("add_tenant_id_to_core_tables")
        runner.rollback_to(tenant_migration_index - 1)
        assert "tenant_id" not in _columns(conn, "sessions")
        assert "tenant_id" not in _columns(conn, "runs")
        version = conn.execute(
            "SELECT version FROM schema_version WHERE namespace = 'store'"
        ).fetchone()[0]
        assert version == tenant_migration_index - 1

        runner.run_pending()
        assert "tenant_id" in _columns(conn, "sessions")
        assert "tenant_id" in _columns(conn, "messages")
        version = conn.execute(
            "SELECT version FROM schema_version WHERE namespace = 'store'"
        ).fetchone()[0]
        assert version == len(STORE_MIGRATIONS)
    finally:
        conn.close()


def test_sqlite_rollback_to_specific_version(tmp_path: Path) -> None:
    """``rollback_to`` reverts every migration above the requested target version."""
    db_path = tmp_path / "rollback.db"
    conn = sqlite3.connect(db_path)
    try:
        runner = MigrationRunner(conn, STORE_MIGRATIONS, namespace="store")
        runner.run_pending()

        runner.rollback_to(4)

        version = conn.execute(
            "SELECT version FROM schema_version WHERE namespace = 'store'"
        ).fetchone()[0]
        assert version == 4
        assert "tenant_id" not in _columns(conn, "sessions")
        assert _columns(conn, "plugins")  # migration 4's table remains
    finally:
        conn.close()


def test_rollback_to_rejects_invalid_targets(tmp_path: Path) -> None:
    """``rollback_to`` refuses a target above the current version or below zero."""
    conn = sqlite3.connect(tmp_path / "invalid.db")
    try:
        runner = MigrationRunner(conn, STORE_MIGRATIONS, namespace="store")
        runner.run_pending()
        with pytest.raises(ValueError):
            runner.rollback_to(len(STORE_MIGRATIONS) + 1)
        with pytest.raises(ValueError):
            runner.rollback_to(-1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PostgreSQL: RLS/tenant_id DDL via the FakeConnection mock pattern
# ---------------------------------------------------------------------------


def test_postgres_store_issues_tenant_rls_ddl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing a :class:`PostgresStore` issues tenant_id + RLS DDL via the versioned runner."""
    connections = install_fake_psycopg(monkeypatch)

    PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    executed_sql = "\n".join(sql for sql, _params in connections[0].executed)
    # Core tables still created (behavior preserved for existing callers).
    assert "CREATE TABLE IF NOT EXISTS sessions" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS runs" in executed_sql
    # New tenancy DDL from the second migration.
    assert "ADD COLUMN IF NOT EXISTS tenant_id" in executed_sql
    assert "ENABLE ROW LEVEL SECURITY" in executed_sql
    assert "FORCE ROW LEVEL SECURITY" in executed_sql
    assert "CREATE POLICY sessions_tenant_isolation" in executed_sql
    assert "current_setting('app.tenant_id', true)" in executed_sql


def test_postgres_migration_rollback_drops_policy_and_column() -> None:
    """The tenant/RLS migration's down step drops the policy, column, and RLS enforcement.

    ``FakeConnection`` (mirroring ``test_postgres_store.py``) does not track real
    schema-version state — ``fetchone()`` always returns ``None`` — so exercising
    the runner's version-aware ``run_down``/``rollback_to`` bookkeeping against it
    would be meaningless. That bookkeeping is covered against a real
    ``sqlite3.Connection`` above; here we assert the migration's ``down`` DDL shape
    directly, exactly as :class:`MigrationRunner` would invoke it.
    """
    conn = FakeConnection()
    tenant_migration = POSTGRES_STORE_MIGRATIONS[1]
    assert isinstance(tenant_migration, Migration)

    tenant_migration.down(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    assert "DROP POLICY IF EXISTS sessions_tenant_isolation" in executed_sql
    assert "DROP COLUMN IF EXISTS tenant_id" in executed_sql
    assert "NO FORCE ROW LEVEL SECURITY" in executed_sql


def test_postgres_plan_tables_migration_issues_tenant_rls_ddl() -> None:
    """The plan store's tenancy migration (E8-S1-T3, appended at the end) issues the expected up DDL.

    Unlike migration 2, this one also guards with ``CREATE TABLE IF NOT
    EXISTS`` (see :func:`add_tenant_id_and_rls_to_plan_tables`'s docstring
    for why), so both the table creation and the tenancy DDL are asserted.
    """
    conn = FakeConnection()
    plan_tenant_migration = POSTGRES_STORE_MIGRATIONS[-1]
    assert isinstance(plan_tenant_migration, Migration)
    assert plan_tenant_migration.name == "add_tenant_id_and_rls_to_plan_tables"

    plan_tenant_migration.up(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    assert "CREATE TABLE IF NOT EXISTS plan_documents" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS plan_approvals" in executed_sql
    assert "ALTER TABLE plan_documents ADD COLUMN IF NOT EXISTS tenant_id" in executed_sql
    assert "ALTER TABLE plan_approvals ADD COLUMN IF NOT EXISTS tenant_id" in executed_sql
    assert "CREATE POLICY plan_documents_tenant_isolation" in executed_sql
    assert "CREATE POLICY plan_approvals_tenant_isolation" in executed_sql
    assert "current_setting('app.tenant_id', true)" in executed_sql


def test_postgres_plan_tables_migration_rollback_drops_policy_and_column() -> None:
    """The plan store's tenancy migration's down step reverts RLS and the ``tenant_id`` column."""
    conn = FakeConnection()
    plan_tenant_migration = POSTGRES_STORE_MIGRATIONS[-1]
    assert isinstance(plan_tenant_migration, Migration)

    plan_tenant_migration.down(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    assert "DROP POLICY IF EXISTS plan_documents_tenant_isolation" in executed_sql
    assert "DROP POLICY IF EXISTS plan_approvals_tenant_isolation" in executed_sql
    assert executed_sql.count("DROP COLUMN IF EXISTS tenant_id") == 2
    assert "NO FORCE ROW LEVEL SECURITY" in executed_sql


# ---------------------------------------------------------------------------
# PostgresStore / PostgresPlanStore: methods scope the connection via
# set_postgres_tenant() before querying (E8-S1-T3)
# ---------------------------------------------------------------------------


def test_postgres_store_create_session_scopes_tenant_before_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    """``create_session`` calls ``set_postgres_tenant`` with the passed tenant before inserting.

    The ``tenant_id`` column is also written explicitly in the ``INSERT``
    (rather than left to its ``DEFAULT 'default'``) because the RLS policy's
    implicit ``WITH CHECK`` (mirroring ``USING`` when none is given) would
    otherwise reject the insert for any non-default tenant.
    """
    connections = install_fake_psycopg(monkeypatch)
    store = PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    store.create_session(session_id="s1", goal="g", plan=[], artifacts={}, tenant_id="acme")

    conn = connections[-1]
    set_tenant_sql, set_tenant_params = conn.executed[0]
    assert "set_config" in set_tenant_sql
    assert set_tenant_params == ("acme",)
    insert_sql, insert_params = conn.executed[1]
    assert "INSERT INTO sessions" in insert_sql
    assert cast(Sequence[object], insert_params)[-1] == "acme"


def test_postgres_store_list_run_steps_scopes_tenant_and_joins_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """``list_run_steps`` scopes the tenant and joins ``runs`` for transitive RLS scoping.

    ``run_steps`` has no ``tenant_id``/RLS of its own (ADR-010) — the
    ``JOIN`` to ``runs`` is what makes tenant isolation actually apply to
    this read.
    """
    connections = install_fake_psycopg(monkeypatch)
    store = PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    store.list_run_steps("run-1", tenant_id="acme")

    conn = connections[-1]
    set_tenant_sql, set_tenant_params = conn.executed[0]
    assert "set_config" in set_tenant_sql
    assert set_tenant_params == ("acme",)
    query_sql, _query_params = conn.executed[1]
    assert "FROM run_steps" in query_sql
    assert "JOIN runs" in query_sql


def test_postgres_store_get_active_score_snapshot_joins_score_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_active_score_snapshot`` scopes the tenant and joins ``score_snapshots``.

    ``score_snapshot_promotions`` has no ``tenant_id``/RLS of its own
    (ADR-010) — the ``JOIN`` to ``score_snapshots`` transitively scopes this
    read to *tenant_id*.
    """
    connections = install_fake_psycopg(monkeypatch)
    store = PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    store.get_active_score_snapshot("policy-1", tenant_id="acme")

    conn = connections[-1]
    set_tenant_sql, set_tenant_params = conn.executed[0]
    assert "set_config" in set_tenant_sql
    assert set_tenant_params == ("acme",)
    query_sql, _query_params = conn.executed[1]
    assert "FROM score_snapshot_promotions" in query_sql
    assert "JOIN score_snapshots" in query_sql


def test_postgres_plan_store_upsert_plan_scopes_tenant_before_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    """``upsert_plan`` calls ``set_postgres_tenant`` with the passed tenant before inserting."""
    connections = install_fake_psycopg(monkeypatch)
    store = PostgresPlanStore(database_url="postgresql://autodev:autodev@postgres/autodev")

    store.upsert_plan("s1", ["step1"], tenant_id="acme")

    conn = connections[-1]
    set_tenant_sql, set_tenant_params = conn.executed[0]
    assert "set_config" in set_tenant_sql
    assert set_tenant_params == ("acme",)
    insert_sql, insert_params = conn.executed[1]
    assert "INSERT INTO plan_documents" in insert_sql
    assert cast(Sequence[object], insert_params)[-1] == "acme"


def test_postgres_plan_store_approve_scopes_tenant_on_both_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """``approve`` threads *tenant_id* through both ``set_status`` and ``_append_approval``."""
    connections = install_fake_psycopg(monkeypatch)
    store = PostgresPlanStore(database_url="postgresql://autodev:autodev@postgres/autodev")

    store.approve("s1", actor="alice", tenant_id="acme")

    # Last two connections opened correspond to set_status then _append_approval.
    status_conn, approval_conn = connections[-2], connections[-1]
    assert status_conn.executed[0][1] == ("acme",)
    assert "UPDATE plan_documents" in status_conn.executed[1][0]
    assert approval_conn.executed[0][1] == ("acme",)
    insert_sql, insert_params = approval_conn.executed[1]
    assert "INSERT INTO plan_approvals" in insert_sql
    assert cast(Sequence[object], insert_params)[-1] == "acme"


# ---------------------------------------------------------------------------
# tenancy.py helpers
# ---------------------------------------------------------------------------


def test_set_postgres_tenant_uses_parameterized_set_config() -> None:
    """``set_postgres_tenant`` uses ``set_config`` (bind-safe), never a literal SET LOCAL string."""
    conn = FakeConnection()

    set_postgres_tenant(conn, "acme")

    sql, params = conn.executed[-1]
    assert "set_config" in sql
    assert "app.tenant_id" in sql
    assert params == ("acme",)


def test_set_postgres_tenant_rejects_empty_tenant() -> None:
    """An empty tenant id is rejected rather than silently scoping to nothing."""
    with pytest.raises(ValueError):
        set_postgres_tenant(FakeConnection(), "")


def test_sqlite_tenant_clause_defaults_and_validates() -> None:
    """``sqlite_tenant_clause`` returns an AND-prefixed fragment and validates its input."""
    clause, params = sqlite_tenant_clause()
    assert clause == "AND tenant_id = ?"
    assert params == (DEFAULT_TENANT_ID,)

    with pytest.raises(ValueError):
        sqlite_tenant_clause("")


def test_sqlite_tenant_clause_custom_param_style() -> None:
    """A caller building dialect-parameterized SQL can request ``%s`` placeholders."""
    clause, params = sqlite_tenant_clause("acme", param_style="%s")
    assert clause == "AND tenant_id = %s"
    assert params == ("acme",)
