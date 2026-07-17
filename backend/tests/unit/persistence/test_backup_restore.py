"""E8-S4-T3 — automated backup/restore round-trip tests.

Round-trip pattern: **seed → backup → wipe → restore → integrity asserts**,
covering the SQLite State Store and the Artifact Store, plus manifest
integrity and CLI exit-code behaviour. PostgreSQL and MinIO variants skip
automatically when the required tooling/services are unavailable.

Periodic execution: this module runs on every CI run and is additionally
meant to run on a schedule (at least weekly) against staging-equivalent
PostgreSQL + MinIO, per
``docs/v2_platform/runbooks/e8_restore_runbook.md`` §7.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from backend.artifacts.store import ArtifactKind, LocalArtifactStore
from backend.persistence.backup import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    BackupError,
    BackupManager,
    main,
)
from backend.persistence.sqlite_adapter import SQLiteStore

_POSTGRES_URL = os.environ.get("AUTODEV_TEST_POSTGRES_URL", "")
_MINIO_ENDPOINT = os.environ.get("AUTODEV_TEST_MINIO_ENDPOINT", "")


def _seed_sqlite(db_path: Path) -> SQLiteStore:
    """Create and seed a SQLite store with a session, run, and messages.

    Args:
        db_path: Filesystem path for the SQLite database file.

    Returns:
        The seeded store.
    """
    store = SQLiteStore(f"sqlite:///{db_path}")
    store.create_session(
        session_id="sess-1",
        goal="prove backups work",
        plan=["step one", "step two"],
        artifacts={"report": "artifacts/report.md"},
    )
    store.create_run(
        run_id="run-1",
        session_id="sess-1",
        status="completed",
        run_type="chat",
        current_state="done",
        trigger_message="hello",
        results=[{"ok": True}],
        steps=[],
    )
    store.append_messages(
        "sess-1",
        "run-1",
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )
    return store


def _seed_artifacts(root: Path) -> LocalArtifactStore:
    """Create a local artifact store seeded with objects in two buckets.

    Args:
        root: Root directory for the local artifact store.

    Returns:
        The seeded store.
    """
    store = LocalArtifactStore(root)
    store.put_artifact(
        ArtifactKind.PATCH, "tenant-a/patches/p1.diff", b"diff-bytes"
    )
    store.put_artifact(
        ArtifactKind.LOG, "tenant-a/runs/run-1/stdout.log", b"log-bytes"
    )
    return store


def test_sqlite_backup_restore_round_trip(tmp_path: Path) -> None:
    """Seed → backup → wipe → restore preserves sessions, runs, messages."""
    db_path = tmp_path / "state" / "autodev.db"
    db_path.parent.mkdir(parents=True)
    _seed_sqlite(db_path)

    manager = BackupManager(database_url=f"sqlite:///{db_path}")
    backup_dir = tmp_path / "backup"
    report = manager.backup(backup_dir)
    assert {c.name: c.status for c in report.components}["sqlite"] == "completed"

    # Wipe.
    db_path.unlink()
    assert not db_path.exists()

    # Restore and assert integrity.
    manager.restore(backup_dir)
    restored = SQLiteStore(f"sqlite:///{db_path}")
    session = restored.get_session("sess-1")
    assert session is not None
    assert session["goal"] == "prove backups work"
    messages = restored.list_messages("sess-1")
    assert [m["content"] for m in messages] == ["hello", "world"]
    runs = restored.list_runs("sess-1")
    assert [r["id"] for r in runs] == ["run-1"]


def test_artifact_mirror_round_trip_local(tmp_path: Path) -> None:
    """Artifacts are mirrored and restored via the public store API only."""
    artifact_root = tmp_path / "artifacts"
    store = _seed_artifacts(artifact_root)
    db_path = tmp_path / "autodev.db"
    _seed_sqlite(db_path)

    manager = BackupManager(
        database_url=f"sqlite:///{db_path}", artifact_store=store
    )
    backup_dir = tmp_path / "backup"
    manager.backup(backup_dir)

    # Wipe the artifact store entirely.
    shutil.rmtree(artifact_root)
    fresh_store = LocalArtifactStore(artifact_root)
    with pytest.raises(FileNotFoundError):
        fresh_store.get_artifact("patch-artifacts", "tenant-a/patches/p1.diff")

    restore_manager = BackupManager(
        database_url=f"sqlite:///{db_path}", artifact_store=fresh_store
    )
    restore_manager.restore(backup_dir)
    assert (
        fresh_store.get_artifact("patch-artifacts", "tenant-a/patches/p1.diff")
        == b"diff-bytes"
    )
    assert (
        fresh_store.get_artifact("logs", "tenant-a/runs/run-1/stdout.log")
        == b"log-bytes"
    )


def test_manifest_has_schema_version_and_digests(tmp_path: Path) -> None:
    """The manifest records schema_version and SHA-256 for every file."""
    db_path = tmp_path / "autodev.db"
    _seed_sqlite(db_path)
    store = _seed_artifacts(tmp_path / "artifacts")

    manager = BackupManager(
        database_url=f"sqlite:///{db_path}", artifact_store=store
    )
    backup_dir = tmp_path / "backup"
    manager.backup(backup_dir)

    manifest = json.loads(
        (backup_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    sqlite_spec = manifest["components"]["sqlite"]
    snapshot = backup_dir / sqlite_spec["file"]
    assert (
        hashlib.sha256(snapshot.read_bytes()).hexdigest()
        == sqlite_spec["sha256"]
    )
    entries = manifest["components"]["artifacts"]["entries"]
    assert len(entries) == 2
    for entry in entries:
        payload = (backup_dir / entry["file"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]


def test_verify_rejects_tampered_backup(tmp_path: Path) -> None:
    """Tampering with a backed-up file makes verify/restore fail."""
    db_path = tmp_path / "autodev.db"
    _seed_sqlite(db_path)
    manager = BackupManager(database_url=f"sqlite:///{db_path}")
    backup_dir = tmp_path / "backup"
    manager.backup(backup_dir)

    snapshot = backup_dir / "state_store.sqlite3"
    snapshot.write_bytes(snapshot.read_bytes() + b"tampered")

    with pytest.raises(BackupError, match="digest mismatch"):
        manager.verify(backup_dir)
    with pytest.raises(BackupError, match="digest mismatch"):
        manager.restore(backup_dir)


def test_verify_rejects_unknown_schema_version(tmp_path: Path) -> None:
    """A manifest with an unsupported schema_version is rejected."""
    db_path = tmp_path / "autodev.db"
    _seed_sqlite(db_path)
    manager = BackupManager(database_url=f"sqlite:///{db_path}")
    backup_dir = tmp_path / "backup"
    manager.backup(backup_dir)

    manifest_path = backup_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupError, match="schema_version"):
        manager.verify(backup_dir)


def test_cli_exits_nonzero_on_failure(tmp_path: Path) -> None:
    """The CLI returns a non-zero exit code when verification fails."""
    missing = tmp_path / "does-not-exist"
    assert main(["verify", "--from", str(missing)]) == 1


def test_backup_fails_when_sqlite_database_missing(tmp_path: Path) -> None:
    """Backing up a nonexistent SQLite database raises BackupError."""
    manager = BackupManager(
        database_url=f"sqlite:///{tmp_path / 'missing.db'}"
    )
    with pytest.raises(BackupError, match="not found"):
        manager.backup(tmp_path / "backup")


@pytest.mark.skipif(
    not _POSTGRES_URL or shutil.which("pg_dump") is None,
    reason="requires AUTODEV_TEST_POSTGRES_URL and pg_dump/pg_restore on PATH",
)
def test_postgres_backup_restore_round_trip(tmp_path: Path) -> None:
    """pg_dump → pg_restore round trip against a disposable database."""
    manager = BackupManager(database_url=_POSTGRES_URL)
    backup_dir = tmp_path / "backup"
    report = manager.backup(backup_dir)
    statuses = {c.name: c.status for c in report.components}
    assert statuses["postgres"] == "completed"
    manager.verify(backup_dir)
    restore_report = manager.restore(backup_dir)
    restore_statuses = {c.name: c.status for c in restore_report.components}
    assert restore_statuses["postgres"] == "completed"


def test_postgres_skipped_without_tooling(tmp_path: Path) -> None:
    """PostgreSQL component is skipped (not failed) when pg_dump is absent."""
    manager = BackupManager(
        database_url="postgresql://autodev:autodev@localhost/autodev"
    )
    if shutil.which("pg_dump") is not None:
        pytest.skip("pg_dump is available; skip-path not exercisable")
    report = manager.backup(tmp_path / "backup")
    statuses = {c.name: c.status for c in report.components}
    assert statuses["postgres"] == "skipped"


@pytest.mark.skipif(
    not _MINIO_ENDPOINT,
    reason="requires AUTODEV_TEST_MINIO_ENDPOINT (and MinIO credentials env)",
)
def test_minio_artifact_mirror_round_trip(tmp_path: Path) -> None:
    """Mirror/restore round trip against a live MinIO endpoint."""
    from backend.artifacts.store import MinioArtifactStore

    store = MinioArtifactStore(
        endpoint=_MINIO_ENDPOINT,
        access_key=os.environ.get("AUTODEV_TEST_MINIO_ACCESS_KEY", ""),
        secret_key=os.environ.get("AUTODEV_TEST_MINIO_SECRET_KEY", ""),
        secure=False,
    )
    pointer = store.put_artifact(
        ArtifactKind.LOG, "tenant-a/backup-test/probe.log", b"minio-bytes"
    )
    db_path = tmp_path / "autodev.db"
    _seed_sqlite(db_path)
    manager = BackupManager(
        database_url=f"sqlite:///{db_path}", artifact_store=store
    )
    backup_dir = tmp_path / "backup"
    manager.backup(backup_dir)
    manager.verify(backup_dir)
    manager.restore(backup_dir)
    assert (
        store.get_artifact(pointer.bucket, pointer.object_key) == b"minio-bytes"
    )
