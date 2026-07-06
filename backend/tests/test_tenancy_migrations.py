"""Tests for the E8-S1 scoped tenancy slice: down migrations and RLS DDL (ADR-010)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.persistence.migrations.postgres_versions import POSTGRES_STORE_MIGRATIONS
from backend.persistence.migrations.runner import Migration, MigrationEntry, MigrationRunner
from backend.persistence.migrations.versions import PLAN_STORE_MIGRATIONS, STORE_MIGRATIONS
from backend.persistence.postgres_adapter import PostgresStore
from backend.persistence.sqlite_adapter import SQLiteStore
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


def _migration_index(
    name: str, migrations: list[MigrationEntry] = STORE_MIGRATIONS
) -> int:
    """Return the 1-based position of the migration named *name* in *migrations*.

    Looking this up by name (rather than hardcoding a step count) keeps
    round-trip tests correct as later stories append more migrations after
    the tenancy one (e.g. E7-S1's ``code_chunks`` table).

    Args:
        name: The migration's ``name`` attribute to search for.
        migrations: Migration list to search; defaults to ``STORE_MIGRATIONS``.
    """
    for index, migration in enumerate(migrations, start=1):
        if getattr(migration, "name", "") == name:
            return index
    raise AssertionError(f"no migration named {name!r} in the given migration list")


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


def test_plan_store_sqlite_migration_up_down_up_roundtrip(tmp_path: Path) -> None:
    """The plan store's tenancy migration adds ``tenant_id`` to both its tables and reverts cleanly."""
    db_path = tmp_path / "plan_roundtrip.db"
    conn = sqlite3.connect(db_path)
    try:
        runner = MigrationRunner(conn, PLAN_STORE_MIGRATIONS, namespace="plan_store")
        runner.run_pending()
        assert "tenant_id" in _columns(conn, "plan_documents")
        assert "tenant_id" in _columns(conn, "plan_approvals")

        tenant_migration_index = _migration_index(
            "add_tenant_id_to_plan_tables", migrations=PLAN_STORE_MIGRATIONS
        )
        runner.rollback_to(tenant_migration_index - 1)
        assert "tenant_id" not in _columns(conn, "plan_documents")
        assert "tenant_id" not in _columns(conn, "plan_approvals")
        version = conn.execute(
            "SELECT version FROM schema_version WHERE namespace = 'plan_store'"
        ).fetchone()[0]
        assert version == tenant_migration_index - 1

        runner.run_pending()
        assert "tenant_id" in _columns(conn, "plan_documents")
        assert "tenant_id" in _columns(conn, "plan_approvals")
        version = conn.execute(
            "SELECT version FROM schema_version WHERE namespace = 'plan_store'"
        ).fetchone()[0]
        assert version == len(PLAN_STORE_MIGRATIONS)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SQLiteStore: tenant isolation across sessions/runs/messages/evals/snapshots
# ---------------------------------------------------------------------------


def test_sqlite_store_sessions_are_tenant_isolated(tmp_path: Path) -> None:
    """Sessions created under one tenant are invisible to another tenant."""
    store = SQLiteStore(f"sqlite:///{tmp_path / 'sessions.db'}")
    store.create_session(session_id="s-a", goal="goal a", plan=[], artifacts={}, tenant_id="a")
    store.create_session(session_id="s-b", goal="goal b", plan=[], artifacts={}, tenant_id="b")

    tenant_a_ids = {row["id"] for row in store.list_sessions(tenant_id="a")}
    tenant_b_ids = {row["id"] for row in store.list_sessions(tenant_id="b")}
    assert tenant_a_ids == {"s-a"}
    assert tenant_b_ids == {"s-b"}
    assert store.get_session("s-b", tenant_id="a") is None
    assert store.get_session("s-a", tenant_id="a") is not None


def test_sqlite_store_runs_and_run_steps_are_tenant_isolated(tmp_path: Path) -> None:
    """Runs, and their transitively-scoped ``run_steps``, are isolated per tenant."""
    store = SQLiteStore(f"sqlite:///{tmp_path / 'runs.db'}")
    store.create_session(session_id="sess", goal="g", plan=[], artifacts={}, tenant_id="a")
    store.create_run(
        run_id="run-a",
        session_id="sess",
        status="running",
        run_type="existing_repo_change",
        current_state="starting",
        trigger_message="go",
        results=[],
        steps=[
            {
                "step_key": "step-1",
                "agent": "coder",
                "status": "done",
                "started_at": "t0",
                "completed_at": "t1",
            }
        ],
        tenant_id="a",
    )
    store.create_run(
        run_id="run-b",
        session_id="sess",
        status="running",
        run_type="existing_repo_change",
        current_state="starting",
        trigger_message="go",
        results=[],
        steps=[],
        tenant_id="b",
    )

    runs_a = store.list_runs("sess", tenant_id="a")
    runs_b = store.list_runs("sess", tenant_id="b")
    assert {r["id"] for r in runs_a} == {"run-a"}
    assert {r["id"] for r in runs_b} == {"run-b"}

    # run_steps has no tenant_id column of its own; scoped transitively via runs.
    assert len(store.list_run_steps("run-a", tenant_id="a")) == 1
    assert store.list_run_steps("run-a", tenant_id="b") == []


def test_sqlite_store_messages_are_tenant_isolated(tmp_path: Path) -> None:
    """Messages appended under one tenant are invisible to another tenant."""
    store = SQLiteStore(f"sqlite:///{tmp_path / 'messages.db'}")
    store.create_session(session_id="sess", goal="g", plan=[], artifacts={}, tenant_id="a")
    store.append_messages("sess", "run-a", [{"role": "user", "content": "hi"}], tenant_id="a")

    assert len(store.list_messages("sess", tenant_id="a")) == 1
    assert store.list_messages("sess", tenant_id="b") == []


def test_sqlite_store_eval_results_are_tenant_isolated(tmp_path: Path) -> None:
    """Eval results created under one tenant are invisible to another tenant."""
    store = SQLiteStore(f"sqlite:///{tmp_path / 'evals.db'}")
    store.create_eval_result(
        eval_id="eval-1",
        eval_version="v1",
        run_id="run-a",
        document={"mode": "offline"},
        tenant_id="a",
    )

    assert store.get_eval_result("eval-1", "v1", "run-a", tenant_id="a") is not None
    assert store.get_eval_result("eval-1", "v1", "run-a", tenant_id="b") is None
    assert len(store.list_eval_results("eval-1", tenant_id="a")) == 1
    assert store.list_eval_results("eval-1", tenant_id="b") == []


def test_sqlite_store_score_snapshots_and_promotions_are_tenant_isolated(tmp_path: Path) -> None:
    """Score snapshots, and their (transitively-scoped) promotions, are isolated per tenant."""
    store = SQLiteStore(f"sqlite:///{tmp_path / 'snapshots.db'}")
    store.create_score_snapshot(
        snapshot_id="snap-a", sample_count=10, document={"score": 1}, tenant_id="a"
    )
    store.record_snapshot_promotion(
        policy_id="policy-1",
        snapshot_id="snap-a",
        baseline_snapshot_id="",
        promoted=True,
        reason="first",
        decided_at="2026-01-01T00:00:00Z",
    )

    assert store.get_score_snapshot("snap-a", tenant_id="a") is not None
    assert store.get_score_snapshot("snap-a", tenant_id="b") is None
    assert len(store.list_score_snapshots(tenant_id="a")) == 1
    assert store.list_score_snapshots(tenant_id="b") == []

    # score_snapshot_promotions has no tenant_id column; scoped transitively via score_snapshots.
    assert store.get_active_score_snapshot("policy-1", tenant_id="a") is not None
    assert store.get_active_score_snapshot("policy-1", tenant_id="b") is None
    assert len(store.list_snapshot_promotions("policy-1", tenant_id="a")) == 1
    assert store.list_snapshot_promotions("policy-1", tenant_id="b") == []


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
