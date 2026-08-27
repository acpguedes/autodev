"""CI step: apply store migrations to an empty PostgreSQL database (E57-S1).

Constructing :class:`PostgresStore` against an empty database already runs
every migration (S1-T2), so this script's own contribution is making that
an explicit, fail-fast CI step rather than an incidental side effect of the
first test that happens to build a store -- plus proving a rollback/upgrade
round trip (S1-T3) the same way
``backend/tests/persistence_contract/test_migrations.py`` does.

Provisions its own throwaway database via ``CREATE DATABASE`` (dropped on
exit) rather than targeting the server's default database directly: since
PostgreSQL 15, a role only gets ``CREATE`` on a database's ``public`` schema
implicitly when it *owns* that database, which is true for a database this
script's own role creates but not for one created by the server's bootstrap
superuser (e.g. ``POSTGRES_DB``) -- the same reason
``backend/tests/persistence_contract/backends.py`` provisions a fresh
database per contract-suite case instead of reusing one.

Usage:
    python scripts/ci_migrations_check.py <postgresql-admin-url>

*<postgresql-admin-url>* is a URL for an existing, reachable database on the
target server (e.g. ``AUTODEV_TEST_POSTGRES_URL``) -- used only to connect
and issue ``CREATE``/``DROP DATABASE``, not as the migration target itself.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from backend.persistence.migrations import MigrationRunner  # noqa: E402
from backend.persistence.migrations.postgres_versions import (  # noqa: E402
    POSTGRES_STORE_MIGRATIONS,
)
from backend.persistence.postgres_adapter import PostgresStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Apply migrations from empty, then prove idempotency and a rollback/upgrade round trip.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``); expects
            exactly one positional argument, an admin PostgreSQL URL.

    Returns:
        ``0`` on success, ``2`` on a usage error. Any migration failure
        propagates as an uncaught exception, so the CI step exits non-zero
        with a full traceback.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: ci_migrations_check.py <admin_database_url>", file=sys.stderr)
        return 2
    admin_url = args[0]

    db_name = f"ci_migrations_check_{uuid.uuid4().hex}"
    base, _, _ = admin_url.rpartition("/")
    database_url = f"{base}/{db_name}"

    print(f"[migrations] provisioning empty database: {db_name}", flush=True)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db_name}"')

    try:
        _check(database_url)
    finally:
        print(f"[migrations] dropping {db_name}", flush=True)
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')

    return 0


def _check(database_url: str) -> None:
    """Apply migrations from empty, then prove an idempotent re-run and a rollback/upgrade round trip."""
    print(f"[migrations] applying from empty: {database_url}", flush=True)
    store = PostgresStore(database_url)

    with store.connect() as conn:
        runner = MigrationRunner(
            conn, POSTGRES_STORE_MIGRATIONS, namespace="store", engine="postgres"
        )

        print("[migrations] re-running pending (expect a no-op)", flush=True)
        runner.run_pending()

        print("[migrations] rolling back one step", flush=True)
        runner.run_down(1)

        print("[migrations] upgrading back to head", flush=True)
        runner.run_pending()

    print(
        "[migrations] OK: from-empty apply, idempotent re-run, and a "
        "rollback/upgrade round trip all succeeded",
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
