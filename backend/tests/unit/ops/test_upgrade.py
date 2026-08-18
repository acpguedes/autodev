"""Tests for backend/ops/upgrade.py (E34-S3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from backend.config.settings import reset_settings_cache
from backend.ops.upgrade import _release_notes_for, run_upgrade
from backend.persistence.database import reset_store_cache


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    reset_settings_cache()
    reset_store_cache()
    yield
    reset_settings_cache()
    reset_store_cache()


def _set_local_env(tmp_path, monkeypatch: pytest.MonkeyPatch, db_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AUTODEV_PROFILE", "local")
    monkeypatch.setenv("AUTODEV_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    reset_settings_cache()


def test_run_upgrade_backs_up_then_migrates_successfully(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "autodev.db"
    _set_local_env(tmp_path, monkeypatch, db_path)
    # `upgrade` targets an already-installed deployment (bootstrap owns the
    # from-nothing case), so the database must already exist.
    from backend.persistence.sqlite_adapter import SQLiteStore

    SQLiteStore(f"sqlite:///{db_path}")

    result = run_upgrade(str(tmp_path / "backup"), target_version="Unreleased")

    assert result.status == "ok"
    assert (tmp_path / "backup").exists()
    assert db_path.exists()
    assert "Unreleased" in result.release_notes


def test_run_upgrade_refuses_when_db_schema_is_newer_than_known(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "autodev.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE schema_version (namespace TEXT NOT NULL PRIMARY KEY, version INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO schema_version (namespace, version) VALUES ('store', 999999)")
    conn.commit()
    conn.close()

    _set_local_env(tmp_path, monkeypatch, db_path)

    result = run_upgrade(str(tmp_path / "backup"))

    assert result.status == "refused"
    assert "newer" in result.detail
    # Backup ran before the refusal, per the story's "back up before migrate" DoD.
    assert (tmp_path / "backup").exists()


def test_run_upgrade_backup_failure_never_attempts_migration(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "autodev.db"
    _set_local_env(tmp_path, monkeypatch, db_path)

    def _fail_backup(self, backup_dir):  # noqa: ANN001, ARG001
        raise RuntimeError("disk full")

    monkeypatch.setattr("backend.persistence.backup.BackupManager.backup", _fail_backup)

    result = run_upgrade(str(tmp_path / "backup"))

    assert result.status == "backup_failed"
    assert "disk full" in result.detail
    assert not db_path.exists()


def test_release_notes_for_finds_the_matching_changelog_section() -> None:
    notes = _release_notes_for("Unreleased")
    assert notes.startswith("## [Unreleased]")


def test_release_notes_for_returns_empty_when_version_not_found() -> None:
    assert _release_notes_for("nonexistent-version-xyz") == ""


def test_release_notes_for_returns_empty_without_a_target_version() -> None:
    assert _release_notes_for(None) == ""
