"""Tests for E50 — PostgreSQL schema, migrations, tenancy and RLS.

Mirrors ``test_tenancy_migrations.py``'s ``FakeConnection``/``FakeCursor``
pattern (a stand-in for a psycopg connection that records executed DDL)
since no live PostgreSQL is available to this test suite; real RLS
enforcement against a running PostgreSQL is exercised in E57 (CI & Real
PostgreSQL E2E, not yet started). SQLite-side assertions run against a real
``sqlite3.Connection``.
"""

from __future__ import annotations

from backend.persistence.migrations.postgres_versions import POSTGRES_STORE_MIGRATIONS
from backend.persistence.migrations.runner import Migration
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
