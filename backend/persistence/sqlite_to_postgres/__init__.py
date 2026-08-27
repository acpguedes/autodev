"""SQLite -> PostgreSQL data migration (E58, ADR-026).

Provides ``autodev database migrate --from sqlite:///... --to postgresql://...``,
registered via :mod:`backend.cli_plugins.database`. See
``docs/v2_platform/phases/e58_sqlite_to_postgres_migration.md`` for the epic
and ``docs/v2_platform/decisions/ADR-026-sqlite-to-postgres-migration.md``
for the design decisions this package implements.
"""

from __future__ import annotations

from backend.persistence.sqlite_to_postgres.plan import MigrationPlan, TablePlan, build_dry_run_plan
from backend.persistence.sqlite_to_postgres.preflight import PreflightReport, run_preflight
from backend.persistence.sqlite_to_postgres.tables import TABLE_COPY_ORDER

__all__ = [
    "MigrationPlan",
    "PreflightReport",
    "TABLE_COPY_ORDER",
    "TablePlan",
    "build_dry_run_plan",
    "run_preflight",
]
