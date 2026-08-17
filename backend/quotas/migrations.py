"""Operational health check for tenant isolation (ADR-019, E11-S3 Task 2).

Every store already auto-applies its own pending migrations on
construction (:class:`~backend.persistence.migrations.runner.MigrationRunner`
via each store's ``__init__``), so there is never a "run the migration"
step distinct from connecting. What this module adds is a read-only,
operator-facing ``--check`` command that verifies the tenant isolation those
migrations are supposed to have produced is actually present on the
*configured* database — the right tool to run after a deploy or before
trusting a new environment, and the diagnostic Task 3's durable quota tables
extend with their own checks.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Any, Iterable

from backend.persistence.migrations.postgres_versions import (
    PLAN_STORE_TENANT_SCOPED_TABLES as PG_PLAN_TABLES,
)
from backend.persistence.migrations.versions import (
    PLAN_STORE_TENANT_SCOPED_TABLES as SQLITE_PLAN_TABLES,
)
from backend.persistence.migrations.versions import TENANT_SCOPED_STORE_TABLES

#: Every table this check expects to carry direct tenant isolation, beyond
#: the core/plan store tables the migration modules already enumerate.
ADDITIONAL_TENANT_SCOPED_TABLES = ("flow_runs", "artifacts", "events")


class TenancyCheckError(RuntimeError):
    """Raised when a configured database is missing expected tenant isolation."""


def _sqlite_table_has_tenant_id(conn: sqlite3.Connection, table: str) -> bool:
    """Return whether *table* has a ``tenant_id`` column in a SQLite database.

    Args:
        conn: Open SQLite connection.
        table: Table name to inspect.

    Returns:
        ``True`` if the table exists and carries a ``tenant_id`` column.
    """
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    return "tenant_id" in columns


def check_sqlite_tenant_isolation(
    conn: sqlite3.Connection, *, tables: Iterable[str] | None = None
) -> list[str]:
    """Return the subset of *tables* missing a ``tenant_id`` column.

    Args:
        conn: Open SQLite connection to inspect.
        tables: Tables to check; defaults to every table this module knows
            should carry tenant isolation.

    Returns:
        Names of tables missing a ``tenant_id`` column, in the order given.
    """
    targets = tuple(tables) if tables is not None else _all_expected_tables()
    return [table for table in targets if not _sqlite_table_has_tenant_id(conn, table)]


def _postgres_table_has_forced_rls(conn: Any, table: str) -> bool:
    """Return whether *table* has forced Row-Level Security in PostgreSQL.

    Args:
        conn: Open psycopg connection (or connection-like object exposing
            ``execute``/cursor semantics compatible with the rest of
            ``backend/persistence/postgres_adapter.py``).
        table: Table name to inspect.

    Returns:
        ``True`` if ``relrowsecurity`` and ``relforcerowsecurity`` are both
        set for ``table``.
    """
    row = conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = %s",
        (table,),
    ).fetchone()
    if row is None:
        return False
    return bool(row[0]) and bool(row[1])


def check_postgres_tenant_isolation(
    conn: Any, *, tables: Iterable[str] | None = None
) -> list[str]:
    """Return the subset of *tables* missing forced Row-Level Security.

    Args:
        conn: Open PostgreSQL connection to inspect.
        tables: Tables to check; defaults to every table this module knows
            should carry tenant isolation.

    Returns:
        Names of tables missing ``ENABLE``/``FORCE ROW LEVEL SECURITY``, in
        the order given.
    """
    targets = tuple(tables) if tables is not None else _all_expected_tables()
    return [table for table in targets if not _postgres_table_has_forced_rls(conn, table)]


def _all_expected_tables() -> tuple[str, ...]:
    """Return every table this module expects to carry tenant isolation."""
    return (
        *TENANT_SCOPED_STORE_TABLES,
        *SQLITE_PLAN_TABLES,
        *PG_PLAN_TABLES,
        *ADDITIONAL_TENANT_SCOPED_TABLES,
    )


def _resolve_database_url() -> str:
    """Return the effective ``DATABASE_URL``, defaulting like the rest of the app."""
    import os

    return os.environ.get("DATABASE_URL", "")


def _run_check() -> list[str]:
    """Run the tenant-isolation check against the configured database.

    Returns:
        Names of tables missing tenant isolation (empty when healthy).
    """
    database_url = _resolve_database_url()
    if database_url.startswith(("postgresql://", "postgres://")):
        import psycopg  # noqa: PLC0415

        with psycopg.connect(database_url) as conn:
            return check_postgres_tenant_isolation(conn)

    from backend.persistence.sqlite_adapter import _resolve_db_path  # noqa: PLC0415

    db_path = _resolve_db_path(database_url)
    with sqlite3.connect(str(db_path)) as conn:
        return check_sqlite_tenant_isolation(conn)


def main(argv: list[str] | None = None) -> int:
    """Run the ``--check`` CLI.

    Args:
        argv: Argument vector; defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` when every expected table has tenant isolation; ``1`` when at
        least one is missing it.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify every expected table carries tenant isolation.",
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0

    missing = _run_check()
    if missing:
        print(
            "Missing tenant isolation on: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1
    print("All expected tables carry tenant isolation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
