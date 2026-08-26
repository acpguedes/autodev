"""Migrate the pre-E55 standalone plan-step-state SQLite file into the State Store (E55-S3).

Before E55, :class:`~backend.plans.step_state.StepApprovalStore` fell back to
a dedicated SQLite file (``AUTODEV_PLAN_STEP_STATE_DB``, default
``./autodev_plan_step_state.db``) whenever ``DATABASE_URL`` was unset or
pointed at PostgreSQL. E55-S1 ported the store onto the shared State Store
(``get_store()``) and removed that fallback, so any state a pre-E55 install
left behind in that legacy file is now invisible to the running application.
This module is the one-time migration path for that specific file -- it is
*not* the broader SQLite -> PostgreSQL data migration (E58), which reads from
the configured ``DATABASE_URL`` itself; the legacy step-state file lives
entirely outside that URL and would otherwise be silently lost (see the E55
phase doc's "out of scope" note).

The migration is read-only against the legacy file: it is never deleted or
modified, so a revert of the E55 port can still read it (E55's documented
rollback posture). Rows whose ``session_id`` has no matching
``plan_documents`` row under their tenant are reported as unresolved and left
unwritten -- never silently dropped -- so an operator can investigate before
deciding what to do with them.

CLI usage::

    python -m backend.persistence.step_state_migration [--source PATH]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import sys
from typing import Any, Optional

from backend.persistence.tenancy import DEFAULT_TENANT_ID
from backend.plans.step_state import StepApprovalStore, legacy_step_state_db_path


@dataclass(frozen=True)
class UnresolvedStepStateRow:
    """A legacy row whose parent plan document could not be resolved.

    Attributes:
        tenant_id: Tenant the row was read under (its own column, or the
            default tenant for a pre-E50-S3 file with no ``tenant_id``).
        session_id: The row's owning session.
        step_index: The row's zero-based step position.
        reason: Human-readable explanation of why the row was not migrated.
    """

    tenant_id: str
    session_id: str
    step_index: int
    reason: str


@dataclass(frozen=True)
class StepStateMigrationReport:
    """Summary of one migration attempt (E55-S3-T1's required report shape).

    Attributes:
        source_path: The legacy SQLite file that was read.
        rows_read: Total rows found in the legacy file (0 if the file or its
            ``plan_step_state`` table does not exist).
        rows_written: Rows successfully migrated into the State Store.
        unresolved: Rows whose parent plan document could not be found --
            reported here, never silently dropped.
    """

    source_path: str
    rows_read: int
    rows_written: int
    unresolved: tuple[UnresolvedStepStateRow, ...] = field(default_factory=tuple)

    @property
    def rows_unresolved(self) -> int:
        """Number of rows that could not be migrated."""
        return len(self.unresolved)

    def summary(self) -> str:
        """Return a one-line human-readable summary of this report."""
        return (
            f"source={self.source_path!r} rows_read={self.rows_read} "
            f"rows_written={self.rows_written} rows_unresolved={self.rows_unresolved}"
        )


def _read_legacy_rows(source_path: Path) -> list[tuple[str, str, int, str, str, str]]:
    """Read every row of a pre-E55 standalone ``plan_step_state`` SQLite file.

    Args:
        source_path: Path to the legacy SQLite file.

    Returns:
        ``(tenant_id, session_id, step_index, content, state, updated_at)``
        tuples, in no particular order; an empty list if the file or its
        ``plan_step_state`` table does not exist. A pre-E50-S3 file with no
        ``tenant_id`` column reports every row under
        :data:`~backend.persistence.tenancy.DEFAULT_TENANT_ID`.
    """
    if not source_path.exists():
        return []
    conn = sqlite3.connect(str(source_path))
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'plan_step_state'"
        ).fetchone()
        if table_exists is None:
            return []
        columns = {row[1] for row in conn.execute("PRAGMA table_info(plan_step_state)").fetchall()}
        tenant_expr = "tenant_id" if "tenant_id" in columns else f"'{DEFAULT_TENANT_ID}'"
        rows = conn.execute(
            f"SELECT {tenant_expr}, session_id, step_index, content, state, updated_at "
            "FROM plan_step_state ORDER BY session_id, step_index"
        ).fetchall()
        return [tuple(row) for row in rows]
    finally:
        conn.close()


def _plan_exists(session_id: str, tenant_id: str, *, plan_store: Any = None) -> bool:
    """Whether *session_id* has a plan document under *tenant_id* in the configured State Store.

    Args:
        session_id: Session to look up.
        tenant_id: Tenant to scope the lookup to.
        plan_store: An existing plan store (``PlanStore()``-shaped); defaults
            to a fresh one bound to the configured ``DATABASE_URL``.

    Returns:
        ``True`` if a matching ``plan_documents`` row exists.
    """
    if plan_store is None:
        from backend.plans import PlanStore  # noqa: PLC0415

        plan_store = PlanStore()
    return plan_store.get_plan(session_id, tenant_id=tenant_id) is not None


def migrate_legacy_step_state(
    *,
    source_path: Optional[Path] = None,
    store: Optional[StepApprovalStore] = None,
    plan_store: Any = None,
) -> StepStateMigrationReport:
    """Migrate rows from the legacy standalone plan-step-state file into the configured State Store.

    The legacy file is never deleted or modified by this function -- E55's
    documented rollback posture is that a revert of the port can still read
    it. Safe to run more than once: already-migrated rows are re-written
    idempotently (:meth:`~backend.plans.step_state.StepApprovalStore.import_legacy_row`),
    and a still-unresolved row is reported again rather than silently
    skipped.

    Args:
        source_path: Legacy SQLite file to read; defaults to
            :func:`~backend.plans.step_state.legacy_step_state_db_path`.
        store: Target :class:`~backend.plans.step_state.StepApprovalStore`;
            defaults to one bound to the configured State Store.
        plan_store: Plan store used to resolve each row's parent
            ``plan_documents`` reference; defaults to one bound to the
            configured ``DATABASE_URL``.

    Returns:
        A summary of rows read, written, and unresolved.
    """
    path = source_path or legacy_step_state_db_path()
    target = store or StepApprovalStore()
    legacy_rows = _read_legacy_rows(path)

    unresolved: list[UnresolvedStepStateRow] = []
    written = 0
    for tenant_id, session_id, step_index, content, state, updated_at in legacy_rows:
        if not _plan_exists(session_id, tenant_id, plan_store=plan_store):
            unresolved.append(
                UnresolvedStepStateRow(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    step_index=step_index,
                    reason=(
                        f"no plan_documents row for session {session_id!r} "
                        f"under tenant {tenant_id!r}"
                    ),
                )
            )
            continue
        target.import_legacy_row(tenant_id, session_id, step_index, content, state, updated_at)
        written += 1

    return StepStateMigrationReport(
        source_path=str(path),
        rows_read=len(legacy_rows),
        rows_written=written,
        unresolved=tuple(unresolved),
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured ``argparse`` parser.
    """
    parser = argparse.ArgumentParser(
        prog="python -m backend.persistence.step_state_migration",
        description=(
            "Migrate a pre-E55 standalone plan-step-state SQLite file into the "
            "configured State Store."
        ),
    )
    parser.add_argument(
        "--source",
        default=None,
        help="legacy SQLite file to read (defaults to AUTODEV_PLAN_STEP_STATE_DB / "
        "./autodev_plan_step_state.db)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        ``0`` always -- unresolved rows are reported, not treated as a
        process failure, since the legacy file is retained for later
        investigation.
    """
    args = _build_parser().parse_args(argv)
    source_path = Path(args.source).expanduser().resolve() if args.source else None
    report = migrate_legacy_step_state(source_path=source_path)
    print(report.summary())
    for row in report.unresolved:
        print(
            f"  unresolved: tenant={row.tenant_id!r} session={row.session_id!r} "
            f"step_index={row.step_index} reason={row.reason}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "StepStateMigrationReport",
    "UnresolvedStepStateRow",
    "main",
    "migrate_legacy_step_state",
]
