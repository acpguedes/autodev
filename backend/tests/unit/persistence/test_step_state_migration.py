"""Tests for the E55-S3 legacy plan-step-state migration.

Builds a pre-E55 standalone SQLite file by hand (the shape
``StepApprovalStore`` used to create ad hoc, with no ``tenant_id`` column --
the oldest possible legacy shape) and proves the migration reads it,
resolves each row's parent ``plan_documents`` reference, writes the
resolvable ones into a target :class:`StepApprovalStore`, reports the
unresolvable ones instead of dropping them, and never touches the legacy
file itself.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

from backend.persistence.sqlite_adapter.plan_store import SQLitePlanStore
from backend.persistence.step_state_migration import migrate_legacy_step_state
from backend.plans.step_state import StepApprovalStore


def _write_legacy_file(path: Path) -> None:
    """Create a pre-E50-S3 standalone ``plan_step_state`` file: no ``tenant_id`` column."""
    conn = sqlite3.connect(str(path))
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
            "INSERT INTO plan_step_state VALUES "
            "('resolvable-session', 0, 'Do the thing', 'approved', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO plan_step_state VALUES "
            "('orphan-session', 0, 'Nobody claims this plan', 'draft', '2026-01-02T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()


def test_migration_reports_rows_read_written_and_unresolved(tmp_path: Path) -> None:
    """A resolvable row is migrated; an orphaned row is reported, not dropped (E55-S3-T1)."""
    legacy_path = tmp_path / "autodev_plan_step_state.db"
    _write_legacy_file(legacy_path)

    plan_store = SQLitePlanStore(db_path=tmp_path / "target.db")
    plan_store.upsert_plan("resolvable-session", ["Do the thing"], tenant_id="default")
    target_store = StepApprovalStore(db_path=tmp_path / "target.db")

    report = migrate_legacy_step_state(
        source_path=legacy_path, store=target_store, plan_store=plan_store
    )

    assert report.rows_read == 2
    assert report.rows_written == 1
    assert report.rows_unresolved == 1
    assert report.unresolved[0].session_id == "orphan-session"
    assert "no plan_documents row" in report.unresolved[0].reason

    migrated = target_store.get_step("resolvable-session", 0, tenant_id="default")
    assert migrated is not None
    assert migrated.content == "Do the thing"
    assert migrated.state.value == "approved"
    assert migrated.updated_at == "2026-01-01T00:00:00Z"

    assert target_store.get_step("orphan-session", 0, tenant_id="default") is None


def test_migration_never_modifies_the_legacy_file(tmp_path: Path) -> None:
    """The legacy file is retained untouched -- E55's documented rollback posture."""
    legacy_path = tmp_path / "autodev_plan_step_state.db"
    _write_legacy_file(legacy_path)

    plan_store = SQLitePlanStore(db_path=tmp_path / "target.db")
    plan_store.upsert_plan("resolvable-session", ["Do the thing"], tenant_id="default")
    target_store = StepApprovalStore(db_path=tmp_path / "target.db")

    migrate_legacy_step_state(source_path=legacy_path, store=target_store, plan_store=plan_store)

    assert legacy_path.exists()
    conn = sqlite3.connect(str(legacy_path))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM plan_step_state").fetchone()
    finally:
        conn.close()
    assert rows[0] == 2, "the legacy file's own rows are untouched by migration"


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Running the migration twice converges rather than erroring or duplicating."""
    legacy_path = tmp_path / "autodev_plan_step_state.db"
    _write_legacy_file(legacy_path)

    plan_store = SQLitePlanStore(db_path=tmp_path / "target.db")
    plan_store.upsert_plan("resolvable-session", ["Do the thing"], tenant_id="default")
    target_store = StepApprovalStore(db_path=tmp_path / "target.db")

    first = migrate_legacy_step_state(source_path=legacy_path, store=target_store, plan_store=plan_store)
    second = migrate_legacy_step_state(source_path=legacy_path, store=target_store, plan_store=plan_store)

    assert first.rows_written == second.rows_written == 1
    assert len(target_store.list_steps("resolvable-session", tenant_id="default")) == 1


def test_migration_of_a_missing_legacy_file_reports_zero_rows(tmp_path: Path) -> None:
    """No legacy file present is a clean, empty report, not an error."""
    target_store = StepApprovalStore(db_path=tmp_path / "target.db")
    report = migrate_legacy_step_state(
        source_path=tmp_path / "does-not-exist.db", store=target_store
    )
    assert report.rows_read == 0
    assert report.rows_written == 0
    assert report.rows_unresolved == 0
