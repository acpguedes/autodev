"""Standalone plan-step-state file migration for E58 (E58-S3-T1).

The legacy standalone ``autodev_plan_step_state.db`` file lives outside
``DATABASE_URL`` entirely, so :mod:`backend.persistence.sqlite_to_postgres.copy`
never sees it -- it is not one of the tables in
:data:`~backend.persistence.sqlite_to_postgres.tables.TABLE_COPY_ORDER`.
E55-S3 already implemented the read side of this exact migration
(:func:`backend.persistence.step_state_migration.migrate_legacy_step_state`);
this module is the thin E58 wrapper that points it at the *destination*
database instead of the process's ambient ``DATABASE_URL``, so E58's
migration writes step state to the PostgreSQL destination being built, not
wherever the running process happens to be configured for (E58-S3-T1's
"coordinating with E55-S3 so the work is done once, not twice").
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.persistence.step_state_migration import (
    StepStateMigrationReport,
    migrate_legacy_step_state,
)


def migrate_step_state_to_destination(
    dest_url: str, *, source_path: Optional[Path] = None
) -> StepStateMigrationReport:
    """Migrate the legacy standalone step-state file into the destination database.

    Args:
        dest_url: Destination PostgreSQL ``DATABASE_URL``.
        source_path: Legacy SQLite file to read; defaults to
            :func:`~backend.plans.step_state.legacy_step_state_db_path`
            (``AUTODEV_PLAN_STEP_STATE_DB`` / ``./autodev_plan_step_state.db``).

    Returns:
        The migration report (rows read/written/unresolved). Never touches
        the legacy file itself (E55-S3's retained-not-deleted rollback
        posture, unchanged by E58).
    """
    from backend.persistence.postgres_adapter import PostgresPlanStore, PostgresStore
    from backend.plans.step_state import StepApprovalStore

    dest_store = PostgresStore(dest_url)
    dest_plan_store = PostgresPlanStore(database_url=dest_url)
    dest_step_store = StepApprovalStore(store=dest_store)
    return migrate_legacy_step_state(
        source_path=source_path, store=dest_step_store, plan_store=dest_plan_store
    )


__all__ = ["migrate_step_state_to_destination"]
