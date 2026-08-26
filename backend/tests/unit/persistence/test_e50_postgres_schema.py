"""Tests for E50 — PostgreSQL schema, migrations, tenancy and RLS.

Mirrors ``test_tenancy_migrations.py``'s ``FakeConnection``/``FakeCursor``
pattern (a stand-in for a psycopg connection that records executed DDL)
since no live PostgreSQL is available to this test suite; real RLS
enforcement against a running PostgreSQL is exercised in E57 (CI & Real
PostgreSQL E2E, not yet started). SQLite-side assertions run against a real
``sqlite3.Connection``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.persistence.migrations.postgres_versions import (
    E50_TENANT_SCOPED_TABLES,
    POSTGRES_STORE_MIGRATIONS,
)
from backend.persistence.migrations.runner import Migration, _as_migration
from backend.plans.step_state import StepApprovalStore
from backend.quotas.migrations import (
    _postgres_expected_tables,
    check_postgres_tenant_isolation,
)
from backend.tests.unit.persistence.test_tenancy_migrations import FakeConnection

#: The thirteen tables this epic brings under versioned migration + RLS.
QUOTA_AND_SECRET_TABLES = (
    "tenant_quota_policies",
    "tenant_usage_windows",
    "run_leases",
    "storage_reservations",
    "request_rate_buckets",
    "secrets",
)

def _migration_named(name: str) -> Migration:
    """Return the :class:`Migration` with *name* from ``POSTGRES_STORE_MIGRATIONS``."""
    for migration in POSTGRES_STORE_MIGRATIONS:
        if isinstance(migration, Migration) and migration.name == name:
            return migration
    raise AssertionError(f"no migration named {name!r}")


class _RlsStatusConnection:
    """A minimal ``pg_class`` stand-in reporting scripted RLS status per table."""

    def __init__(self, rls_enabled: set[str]) -> None:
        self._rls_enabled = rls_enabled

    def execute(self, sql: str, params: tuple[str, ...] = ()) -> "_RlsStatusConnection":
        assert "pg_class" in sql
        self._queried_table = params[0]
        return self

    def fetchone(self) -> tuple[bool, bool] | None:
        if self._queried_table in self._rls_enabled:
            return (True, True)
        return None


def _migration_index(name: str) -> int:
    """Return the 1-based position of the migration named *name*."""
    for index, migration in enumerate(POSTGRES_STORE_MIGRATIONS, start=1):
        if isinstance(migration, Migration) and migration.name == name:
            return index
    raise AssertionError(f"no migration named {name!r}")


# ---------------------------------------------------------------------------
# E50-S1 — quota and secret tables
# ---------------------------------------------------------------------------


def test_quota_and_secret_tables_migration_creates_all_six() -> None:
    """The up migration issues ``CREATE TABLE`` for every quota/secret table."""
    conn = FakeConnection()
    migration = _migration_named("create_quota_and_secret_tables")

    migration.up(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    for table in QUOTA_AND_SECRET_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in executed_sql
    assert "JSONB NOT NULL" in executed_sql
    assert "TIMESTAMPTZ NOT NULL" in executed_sql
    assert "PRIMARY KEY (tenant_id, project, name, version)" in executed_sql


def test_quota_and_secret_tables_migration_down_drops_all_six() -> None:
    """The down migration drops every quota/secret table it created."""
    conn = FakeConnection()
    migration = _migration_named("create_quota_and_secret_tables")

    migration.down(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    for table in QUOTA_AND_SECRET_TABLES:
        assert f"DROP TABLE IF EXISTS {table}" in executed_sql


def test_quota_and_secret_migration_appended_without_reordering() -> None:
    """The new migration is appended immediately after ``run_step_position``, never reordering it."""
    assert _migration_index("create_quota_and_secret_tables") == _migration_index("run_step_position") + 1


# ---------------------------------------------------------------------------
# E50-S2 — execution policy and environment tables
# ---------------------------------------------------------------------------

POLICY_AND_ENVIRONMENT_TABLES = (
    "execution_policy_rules",
    "execution_dynamic_permissions",
    "execution_policy_decisions",
    "pending_action_decisions",
    "execution_environments",
    "execution_environment_decisions",
)


def test_policy_and_environment_tables_migration_creates_all_six() -> None:
    """The up migration issues ``CREATE TABLE`` for every policy/environment table."""
    conn = FakeConnection()
    migration = _migration_named("create_policy_and_environment_tables")

    migration.up(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    for table in POLICY_AND_ENVIRONMENT_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in executed_sql
    # Pending-decision lookup and expiry-scan indexes called out by E50-S2-T3.
    assert "idx_pg_pending_action_decisions_tenant_run" in executed_sql
    assert "idx_pg_pending_action_decisions_tenant_status" in executed_sql
    assert "ON pending_action_decisions(tenant_id, status, expires_at)" in executed_sql


def test_policy_and_environment_tables_migration_down_drops_all_six() -> None:
    """The down migration drops every policy/environment table it created."""
    conn = FakeConnection()
    migration = _migration_named("create_policy_and_environment_tables")

    migration.down(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    for table in POLICY_AND_ENVIRONMENT_TABLES:
        assert f"DROP TABLE IF EXISTS {table}" in executed_sql


def test_policy_and_environment_migration_appended_after_quota_and_secret() -> None:
    """The policy/environment migration is appended right after the quota/secret one."""
    assert (
        _migration_index("create_policy_and_environment_tables")
        == _migration_index("create_quota_and_secret_tables") + 1
    )


# ---------------------------------------------------------------------------
# E50-S3 — plan_step_state redesign
# ---------------------------------------------------------------------------


def test_plan_step_state_migration_creates_table_with_tenant_and_fk() -> None:
    """The up migration creates ``plan_step_state`` with ``tenant_id`` and a parent foreign key."""
    conn = FakeConnection()
    migration = _migration_named("create_plan_step_state_table")

    migration.up(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    assert "CREATE TABLE IF NOT EXISTS plan_step_state" in executed_sql
    assert "tenant_id TEXT NOT NULL DEFAULT 'default'" in executed_sql
    assert "REFERENCES plan_documents(session_id)" in executed_sql
    assert "idx_pg_plan_step_state_tenant_session" in executed_sql


def test_plan_step_state_migration_down_drops_table() -> None:
    """The down migration drops ``plan_step_state``."""
    conn = FakeConnection()
    migration = _migration_named("create_plan_step_state_table")

    migration.down(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    assert "DROP TABLE IF EXISTS plan_step_state" in executed_sql


def test_plan_step_state_migration_appended_after_policy_and_environment() -> None:
    """The ``plan_step_state`` migration is appended after the policy/environment one."""
    assert (
        _migration_index("create_plan_step_state_table")
        == _migration_index("create_policy_and_environment_tables") + 1
    )


def test_plan_step_state_migration_runs_after_plan_documents_exists() -> None:
    """``plan_step_state``'s foreign key target, ``plan_documents``, is created earlier in the list."""
    assert _migration_index("add_tenant_id_and_rls_to_plan_tables") < _migration_index(
        "create_plan_step_state_table"
    )


def test_sqlite_plan_step_state_fresh_db_has_tenant_id(tmp_path: Path) -> None:
    """A freshly created ``plan_step_state`` SQLite table carries ``tenant_id`` defaulted to ``'default'``."""
    db_path = tmp_path / "step_state.db"
    StepApprovalStore(db_path=db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(plan_step_state)").fetchall()}
        assert "tenant_id" in columns
    finally:
        conn.close()


def test_sqlite_plan_step_state_backfills_existing_rows_to_default_tenant(tmp_path: Path) -> None:
    """Opening a pre-E50-S3 ``plan_step_state`` database adds ``tenant_id`` and backfills existing rows."""
    db_path = tmp_path / "legacy_step_state.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE plan_step_state (
                session_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                state TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, step_index)
            )
            """
        )
        conn.execute(
            "INSERT INTO plan_step_state VALUES ('s1', 0, 'do the thing', 'draft', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()

    StepApprovalStore(db_path=db_path)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT tenant_id FROM plan_step_state WHERE session_id = 's1'").fetchone()
        assert row is not None
        assert row[0] == "default"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# E50-S4 — Row-Level Security and isolation proof
# ---------------------------------------------------------------------------


def test_apply_rls_migration_covers_all_thirteen_tables() -> None:
    """The RLS migration enables, forces, and policy-scopes every one of the thirteen tables."""
    conn = FakeConnection()
    migration = _migration_named("apply_tenant_rls_to_new_tables")

    migration.up(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    for table in E50_TENANT_SCOPED_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in executed_sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in executed_sql
        assert f"CREATE POLICY {table}_tenant_isolation ON {table}" in executed_sql
    assert executed_sql.count("current_setting('app.tenant_id', true)") == len(E50_TENANT_SCOPED_TABLES)
    assert len(E50_TENANT_SCOPED_TABLES) == 13


def test_apply_rls_migration_down_reverts_without_touching_tenant_id_column() -> None:
    """The down step drops RLS enforcement but never drops ``tenant_id`` (owned by the creation migrations)."""
    conn = FakeConnection()
    migration = _migration_named("apply_tenant_rls_to_new_tables")

    migration.down(conn)

    executed_sql = "\n".join(sql for sql, _params in conn.executed)
    for table in E50_TENANT_SCOPED_TABLES:
        assert f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}" in executed_sql
        assert f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY" in executed_sql
        assert f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY" in executed_sql
    assert "DROP COLUMN" not in executed_sql


def test_apply_rls_migration_appended_last_after_plan_step_state() -> None:
    """The RLS migration is the final step, applied after all thirteen tables exist."""
    assert (
        _migration_index("apply_tenant_rls_to_new_tables")
        == _migration_index("create_plan_step_state_table") + 1
    )
    assert _migration_index("apply_tenant_rls_to_new_tables") == len(POSTGRES_STORE_MIGRATIONS)


def test_migration_round_trip_up_down_up_is_idempotent_in_sequence() -> None:
    """Running every migration's up, then every down in reverse, then up again replays cleanly."""
    conn = FakeConnection()
    migrations = [_as_migration(entry) for entry in POSTGRES_STORE_MIGRATIONS]
    for migration in migrations:
        migration.up(conn)
    for migration in reversed(migrations):
        migration.down(conn)
    for migration in migrations:
        migration.up(conn)  # must not raise on a scripted-fresh re-application


def test_quotas_migrations_verifier_includes_all_thirteen_e50_tables() -> None:
    """E50-S4-T2: the PostgreSQL tenancy verifier's default scope covers all thirteen new tables."""
    expected = _postgres_expected_tables()
    for table in E50_TENANT_SCOPED_TABLES:
        assert table in expected


def test_check_postgres_tenant_isolation_flags_missing_rls_on_new_tables() -> None:
    """A table missing forced RLS is reported; one with it is not (E50-S4-T3 DDL-level proof)."""
    conn = _RlsStatusConnection(rls_enabled=set())

    missing = check_postgres_tenant_isolation(conn, tables=E50_TENANT_SCOPED_TABLES)

    assert set(missing) == set(E50_TENANT_SCOPED_TABLES)


def test_check_postgres_tenant_isolation_passes_when_all_thirteen_have_forced_rls() -> None:
    """Once every table reports forced RLS, the verifier finds nothing missing."""
    conn = _RlsStatusConnection(rls_enabled=set(E50_TENANT_SCOPED_TABLES))

    missing = check_postgres_tenant_isolation(conn, tables=E50_TENANT_SCOPED_TABLES)

    assert missing == []
