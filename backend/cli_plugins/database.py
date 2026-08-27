"""CLI plugin for the SQLite -> PostgreSQL data migration (E58).

Registers subcommands via the ``backend.cli_plugins`` auto-loader:

* ``autodev database migrate --from <sqlite-url> --to <postgres-url> [--dry-run]
  [--confirm-nonempty-destination]``
  Run (or plan) a one-way migration from an existing SQLite installation to
  PostgreSQL. See ``docs/v2_platform/decisions/ADR-026-sqlite-to-postgres-migration.md``
  for the design this command implements, and
  ``docs/v2_platform/phases/e58_sqlite_to_postgres_migration.md`` for the epic.

This is deliberately an operator-only CLI command, never exposed through the
``/v2`` API: the migrator reads across every tenant by nature, which Row-Level
Security cannot constrain (ADR-026 decision 3).

No edits to ``backend.cli`` are required — the auto-loader handles
registration via ``register(subparsers)`` automatically.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from backend.persistence.sqlite_to_postgres.plan import MigrationPlan, build_dry_run_plan
from backend.persistence.sqlite_to_postgres.runner import run_migration


def _plan_to_dict(plan: MigrationPlan) -> dict:
    """Build the JSON-serializable shape of a dry-run plan."""
    return {
        "preflight": asdict(plan.preflight),
        "destination_schema_applied": plan.destination_schema_applied,
        "total_source_rows": plan.total_source_rows,
        "tables": [asdict(t) for t in plan.tables],
    }


def _print_progress(table: str, rows_copied: int) -> None:
    print(f"  {table}: {rows_copied} rows copied", file=sys.stderr)


def _handle_migrate(args: argparse.Namespace) -> int:
    if args.dry_run:
        plan = build_dry_run_plan(
            args.source,
            args.dest,
            confirm_nonempty_destination=args.confirm_nonempty_destination,
        )
        print(json.dumps(_plan_to_dict(plan), indent=2))
        return 0 if plan.preflight.passed else 1

    result = run_migration(
        args.source,
        args.dest,
        confirm_nonempty_destination=args.confirm_nonempty_destination,
        report_path=Path(args.report) if args.report else None,
        on_progress=_print_progress,
    )
    print(json.dumps(result.as_dict(), indent=2))
    if not result.preflight.passed:
        return 1
    return 0 if result.safe_to_cut_over else 1


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the ``database`` subcommand group with *subparsers*."""
    database_parser = subparsers.add_parser(
        "database", help="Manage the State Store database (backup, migration)."
    )
    database_sub = database_parser.add_subparsers(dest="database_subcommand")
    database_sub.required = True

    migrate_parser = database_sub.add_parser(
        "migrate", help="Migrate an existing SQLite installation to PostgreSQL (E58)."
    )
    migrate_parser.add_argument(
        "--from", dest="source", required=True, help="Source sqlite:// DATABASE_URL."
    )
    migrate_parser.add_argument(
        "--to", dest="dest", required=True, help="Destination postgresql:// DATABASE_URL."
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the migration plan (preflight + per-table row counts) and write nothing.",
    )
    migrate_parser.add_argument(
        "--confirm-nonempty-destination",
        action="store_true",
        help="Proceed even though the destination already contains data.",
    )
    migrate_parser.add_argument(
        "--report",
        default=None,
        help="Path to persist the full migration/reconciliation report as JSON "
        "(ignored with --dry-run). Never contains a raw connection string.",
    )
    migrate_parser.set_defaults(handler=_handle_migrate)
