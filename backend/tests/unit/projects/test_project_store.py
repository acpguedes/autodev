"""E62-S2: projects store, migration idempotency and backfill (SQLite)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.postgres_versions import E62_TENANT_SCOPED_TABLES, POSTGRES_STORE_MIGRATIONS
from backend.persistence.migrations.versions import STORE_MIGRATIONS
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.projects import ProjectStore


def test_store_create_activate_and_idempotent_root(tmp_path: Path) -> None:
    store = ProjectStore(store=SQLiteStore(f"sqlite:///{tmp_path / 's.db'}"))
    a = store.create(tenant_id="t", name="a", root_path=tmp_path / "a", activate=True)
    b = store.create(tenant_id="t", name="b", root_path=tmp_path / "b")
    assert store.create(tenant_id="t", name="dup", root_path=tmp_path / "a").project_id == a.project_id
    assert store.get_active(tenant_id="t").project_id == a.project_id
    store.activate(b.project_id, tenant_id="t")
    assert store.get_active(tenant_id="t").project_id == b.project_id
    assert {p.project_id: p.is_active for p in store.list(tenant_id="t")} == {a.project_id: False, b.project_id: True}
    with pytest.raises(KeyError):
        store.activate("missing", tenant_id="t")


def test_migration_backfills_pre_existing_sessions_and_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "legacy-proj"
    root.mkdir()
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(root))
    conn = sqlite3.connect(tmp_path / "legacy.db")
    MigrationRunner(conn, STORE_MIGRATIONS[:-1], namespace="store").run_pending()
    for sid, tenant in (("s1", "default"), ("s2", "default"), ("s3", "other")):
        conn.execute(
            "INSERT INTO sessions (id, goal, plan_json, artifacts_json, tenant_id) VALUES (?, 'g', '[]', '{}', ?)",
            (sid, tenant),
        )
    conn.commit()

    MigrationRunner(conn, STORE_MIGRATIONS, namespace="store").run_pending()
    MigrationRunner(conn, STORE_MIGRATIONS, namespace="store").run_pending()

    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE project_id IS NULL").fetchone()[0] == 0
    rows = conn.execute("SELECT tenant_id, project_id, name, root_path, is_active FROM projects ORDER BY tenant_id").fetchall()
    assert rows == [
        ("default", "default", "legacy-proj", str(root.resolve()), 1),
        ("other", "default", "legacy-proj", str(root.resolve()), 1),
    ]


def test_postgres_migration_applies_forced_rls_and_backfill() -> None:
    migration = next(m for m in POSTGRES_STORE_MIGRATIONS if getattr(m, "name", "") == "create_projects_table")
    executed: list[str] = []

    class _Conn:
        def execute(self, sql, params=None):
            executed.append(" ".join(str(sql).split()))

    migration.up(_Conn())
    text = "\n".join(executed)
    assert E62_TENANT_SCOPED_TABLES == ("projects",)
    assert "ALTER TABLE projects FORCE ROW LEVEL SECURITY" in text
    assert "CREATE POLICY projects_tenant_isolation ON projects" in text
    assert "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS project_id TEXT" in text
    assert "UPDATE sessions SET project_id" in text
    assert executed[-5:][0].startswith("ALTER TABLE sessions FORCE ROW LEVEL SECURITY")
