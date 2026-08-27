"""SQLite -> PostgreSQL data migration (E58, ADR-026).

Provides ``autodev database migrate --from sqlite:///... --to postgresql://...``,
registered via :mod:`backend.cli_plugins.database`. See
``docs/v2_platform/phases/e58_sqlite_to_postgres_migration.md`` for the epic
and ``docs/v2_platform/decisions/ADR-026-sqlite-to-postgres-migration.md``
for the design decisions this package implements.
"""

from __future__ import annotations

from backend.persistence.sqlite_to_postgres.artifacts import (
    DanglingArtifactPointer,
    find_dangling_artifact_pointers,
)
from backend.persistence.sqlite_to_postgres.copy import TableCopyResult, copy_all_tables, copy_table
from backend.persistence.sqlite_to_postgres.plan import MigrationPlan, TablePlan, build_dry_run_plan
from backend.persistence.sqlite_to_postgres.preflight import PreflightReport, run_preflight
from backend.persistence.sqlite_to_postgres.reconcile import (
    ReconciliationReport,
    TableReconciliation,
    reconcile_all_tables,
    reconcile_table,
)
from backend.persistence.sqlite_to_postgres.runner import MigrationResult, run_migration
from backend.persistence.sqlite_to_postgres.step_state import migrate_step_state_to_destination
from backend.persistence.sqlite_to_postgres.tables import TABLE_COPY_ORDER

__all__ = [
    "DanglingArtifactPointer",
    "MigrationPlan",
    "MigrationResult",
    "PreflightReport",
    "ReconciliationReport",
    "TABLE_COPY_ORDER",
    "TableCopyResult",
    "TablePlan",
    "TableReconciliation",
    "build_dry_run_plan",
    "copy_all_tables",
    "copy_table",
    "find_dangling_artifact_pointers",
    "migrate_step_state_to_destination",
    "reconcile_all_tables",
    "reconcile_table",
    "run_migration",
    "run_preflight",
]
