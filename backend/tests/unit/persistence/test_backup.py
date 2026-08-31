"""Unit tests for backend/persistence/backup.py (E12-S1).

``backend/tests/test_backup_restore.py`` already covers the SQLite +
local-artifact happy-path round trip end to end. This module fills the
remaining branches: the PostgreSQL component's success/failure paths
(``shutil.which``/``subprocess.run`` monkeypatched, no real ``pg_dump``/
``pg_restore`` required); ``verify()``'s missing-file and digest-mismatch
branches for ``postgres``/``artifacts``; the "skipped" and error branches
of ``_restore_artifacts``/``_restore_postgres``/``_restore_sqlite`` and
``_iter_object_keys``; ``BackupReport.skipped``; and ``main()``'s
``backup``/``restore`` CLI subcommands (``get_settings``/
``get_artifact_store`` monkeypatched). No live services or network access
are required.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from backend.artifacts.store import ArtifactKind, ArtifactStore, LocalArtifactStore
from backend.persistence.backup import (
    MANIFEST_FILENAME,
    BackupError,
    BackupManager,
    BackupReport,
    ComponentResult,
    _dumped_postgres_tables,
    _missing_postgres_tables,
    main,
)
from backend.persistence.backup_status import BackupStatusStore


def _make_sqlite_db(path: Path) -> None:
    """Create a minimal, valid SQLite database file at *path*.

    Args:
        path: Destination file path; parent directories are created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO t (id) VALUES (1)")
        conn.commit()
    finally:
        conn.close()


class _FakeCompletedProcess:
    """Minimal stand-in for :class:`subprocess.CompletedProcess`."""

    def __init__(self, returncode: int, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


# _backup_postgres


def test_backup_postgres_skipped_when_database_url_not_postgres(tmp_path: Path) -> None:
    """A non-``postgresql://`` DATABASE_URL skips the postgres component."""
    manager = BackupManager(database_url="sqlite:///x.db")
    manifest: dict[str, Any] = {"components": {}}
    result = manager._backup_postgres(tmp_path, manifest)
    assert result == ComponentResult("postgres", "skipped", "DATABASE_URL is not postgresql://")
    assert manifest["components"]["postgres"] == {"status": "skipped"}


def test_backup_postgres_fails_when_pg_dump_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured PostgreSQL backup with no ``pg_dump`` on PATH fails closed."""
    monkeypatch.setattr("shutil.which", lambda _: None)
    manager = BackupManager(
        database_url="postgresql://svc:db-secret@postgres/autodev"
    )

    with pytest.raises(
        BackupError,
        match="PostgreSQL backup is configured but pg_dump is not available",
    ):
        manager._backup_postgres(tmp_path, {"components": {}})


def test_backup_postgres_uses_pgpassword_and_omits_password_from_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The password reaches pg_dump only via PGPASSWORD, never argv or errors."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pg_dump")
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        for arg in cmd:
            if arg.startswith("--file="):
                Path(arg.removeprefix("--file=")).write_bytes(b"dump-bytes")
        return _FakeCompletedProcess(returncode=1, stderr="auth failed for svc")

    monkeypatch.setattr("subprocess.run", fake_run)
    manager = BackupManager(
        database_url="postgresql://svc:db-secret@localhost/autodev"
    )

    with pytest.raises(BackupError) as excinfo:
        manager._backup_postgres(tmp_path, {"components": {}})

    assert "db-secret" not in str(excinfo.value)
    assert not any("db-secret" in arg for arg in captured["cmd"])
    assert captured["env"]["PGPASSWORD"] == "db-secret"


def test_backup_postgres_completed_writes_manifest_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful ``pg_dump`` run records a completed component with digest."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        "backend.persistence.backup._live_postgres_tables",
        lambda connection_url: ["sessions"],
    )
    monkeypatch.setattr(
        "backend.persistence.backup._postgres_vector_extension_state",
        lambda connection_url: {"version": "0.8.0", "indexes": ["code_embeddings_hnsw"]},
    )

    def fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        if "--list" in cmd:
            return _FakeCompletedProcess(
                returncode=0,
                stdout="1; 1259 16400 TABLE public sessions autodev\n",
            )
        for arg in cmd:
            if arg.startswith("--file="):
                Path(arg.removeprefix("--file=")).write_bytes(b"dump-bytes")
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    manager = BackupManager(database_url="postgresql://autodev@localhost/autodev")
    manifest: dict[str, Any] = {"components": {}}
    result = manager._backup_postgres(tmp_path, manifest)

    assert result.status == "completed"
    entry = manifest["components"]["postgres"]
    assert entry["size_bytes"] == len(b"dump-bytes")
    assert entry["sha256"] == __import__("hashlib").sha256(b"dump-bytes").hexdigest()
    assert entry["tables"] == ["sessions"]
    assert entry["table_count"] == 1
    assert entry["extension"] == {"version": "0.8.0", "indexes": ["code_embeddings_hnsw"]}


def test_backup_postgres_raises_on_pg_dump_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero ``pg_dump`` exit code raises ``BackupError`` with stderr."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pg_dump")
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _FakeCompletedProcess(returncode=1, stderr="connection refused"),
    )
    manager = BackupManager(database_url="postgresql://autodev@localhost/autodev")
    with pytest.raises(BackupError, match="pg_dump failed: connection refused"):
        manager._backup_postgres(tmp_path, {"components": {}})


# _missing_postgres_tables / _dumped_postgres_tables (E59-S1-T1)


def test_missing_postgres_tables_is_empty_when_dump_covers_every_live_table() -> None:
    """No coverage gap when every live table appears in the dump's TOC."""
    assert _missing_postgres_tables(["sessions", "runs"], ["runs", "sessions"]) == []


def test_missing_postgres_tables_reports_a_deliberately_added_uncovered_table() -> None:
    """Negative control: a live table absent from the dump TOC is reported."""
    assert _missing_postgres_tables(
        ["sessions", "runs", "plan_step_state"], ["sessions", "runs"]
    ) == ["plan_step_state"]


def test_dumped_postgres_tables_parses_toc_and_ignores_table_data_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TOC parsing extracts ``public`` schema table names, skipping ``TABLE DATA``, comments, and other schemas."""
    toc = "\n".join(
        [
            ";",
            "; Archive created at 2026-01-01 00:00:00 UTC",
            ";     dbname: autodev",
            "3283; 1259 16584 TABLE public code_chunks autodev",
            "3284; 1259 16590 TABLE public code_embeddings autodev",
            "3285; 1259 16600 TABLE internal audit_log autodev",
            "3450; 0 16584 TABLE DATA public code_chunks autodev",
            "",
        ]
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _FakeCompletedProcess(returncode=0, stdout=toc),
    )
    tables = _dumped_postgres_tables("/usr/bin/pg_restore", tmp_path / "dump.pgdump")
    assert tables == ["code_chunks", "code_embeddings"]


def test_dumped_postgres_tables_raises_when_pg_restore_list_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero ``pg_restore --list`` exit code raises ``BackupError``."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _FakeCompletedProcess(returncode=1, stderr="not an archive"),
    )
    with pytest.raises(BackupError, match="pg_restore --list failed: not an archive"):
        _dumped_postgres_tables("/usr/bin/pg_restore", tmp_path / "dump.pgdump")


# _restore_postgres


def test_restore_postgres_skipped_when_not_in_backup() -> None:
    """An empty component spec (absent from the manifest) skips restore."""
    manager = BackupManager(database_url="postgresql://autodev@localhost/autodev")
    result = manager._restore_postgres(Path("/nonexistent"), {})
    assert result == ComponentResult("postgres", "skipped", "not in backup")


def test_restore_postgres_fails_when_pg_restore_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed PostgreSQL manifest entry with no ``pg_restore`` fails closed."""
    monkeypatch.setattr("shutil.which", lambda _: None)
    manager = BackupManager(
        database_url="postgresql://svc:db-secret@localhost/autodev"
    )
    spec = {"status": "completed", "file": "state_store.pgdump"}

    with pytest.raises(
        BackupError,
        match="PostgreSQL restore is configured but pg_restore is not available",
    ):
        manager._restore_postgres(tmp_path, spec)


def test_restore_postgres_uses_pgpassword_and_omits_password_from_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The password reaches pg_restore only via PGPASSWORD, never argv or errors."""
    (tmp_path / "state_store.pgdump").write_bytes(b"dump-bytes")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pg_restore")
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return _FakeCompletedProcess(returncode=1, stderr="auth failed for svc")

    monkeypatch.setattr("subprocess.run", fake_run)
    manager = BackupManager(
        database_url="postgresql://svc:db-secret@localhost/autodev"
    )
    spec = {"status": "completed", "file": "state_store.pgdump"}

    with pytest.raises(BackupError) as excinfo:
        manager._restore_postgres(tmp_path, spec)

    assert "db-secret" not in str(excinfo.value)
    assert not any("db-secret" in arg for arg in captured["cmd"])
    assert captured["env"]["PGPASSWORD"] == "db-secret"


def test_restore_postgres_raises_when_database_url_not_postgres(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backup with a postgres dump cannot be restored into a non-postgres URL."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pg_restore")
    manager = BackupManager(database_url="sqlite:///x.db")
    spec = {"status": "completed", "file": "state_store.pgdump"}
    with pytest.raises(BackupError, match="DATABASE_URL is not"):
        manager._restore_postgres(tmp_path, spec)


def test_restore_postgres_raises_on_pg_restore_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero ``pg_restore`` exit code raises ``BackupError`` with stderr."""
    (tmp_path / "state_store.pgdump").write_bytes(b"dump-bytes")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pg_restore")
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _FakeCompletedProcess(returncode=1, stderr="role does not exist"),
    )
    manager = BackupManager(database_url="postgresql://autodev@localhost/autodev")
    spec = {"status": "completed", "file": "state_store.pgdump"}
    with pytest.raises(BackupError, match="pg_restore failed: role does not exist"):
        manager._restore_postgres(tmp_path, spec)


def test_restore_postgres_completed_when_pg_restore_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero exit code from ``pg_restore`` reports the component as completed."""
    (tmp_path / "state_store.pgdump").write_bytes(b"dump-bytes")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pg_restore")
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: _FakeCompletedProcess(returncode=0))
    manager = BackupManager(database_url="postgresql://autodev@localhost/autodev")
    spec = {"status": "completed", "file": "state_store.pgdump"}
    result = manager._restore_postgres(tmp_path, spec)
    assert result == ComponentResult("postgres", "completed")


# _backup_sqlite / _restore_sqlite


def test_backup_sqlite_skipped_when_database_url_not_sqlite(tmp_path: Path) -> None:
    """A non-``sqlite://`` DATABASE_URL skips the sqlite component."""
    manager = BackupManager(database_url="postgresql://autodev@localhost/autodev")
    result = manager._backup_sqlite(tmp_path, {"components": {}})
    assert result.status == "skipped"
    assert "not sqlite" in result.detail


def test_restore_sqlite_skipped_when_not_in_backup(tmp_path: Path) -> None:
    """An empty component spec (absent from the manifest) skips restore."""
    manager = BackupManager(database_url="sqlite:///x.db")
    result = manager._restore_sqlite(tmp_path, {})
    assert result == ComponentResult("sqlite", "skipped", "not in backup")


def test_restore_sqlite_raises_when_database_url_not_sqlite(tmp_path: Path) -> None:
    """A backup with a sqlite snapshot cannot be restored into a non-sqlite URL."""
    snapshot = tmp_path / "state_store.sqlite3"
    _make_sqlite_db(snapshot)
    manager = BackupManager(database_url="postgresql://autodev@localhost/autodev")
    spec = {"status": "completed", "file": "state_store.sqlite3"}
    with pytest.raises(BackupError, match="DATABASE_URL is not sqlite"):
        manager._restore_sqlite(tmp_path, spec)


# verify()


def _write_manifest(backup_dir: Path, components: dict[str, Any]) -> None:
    """Write a minimal, schema-valid manifest with the given component specs.

    Args:
        backup_dir: Directory to write ``manifest.json`` into.
        components: The ``components`` mapping to embed in the manifest.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / MANIFEST_FILENAME).write_text(
        json.dumps({"schema_version": 1, "components": components}), encoding="utf-8"
    )


def test_verify_raises_when_manifest_missing(tmp_path: Path) -> None:
    """Verifying a directory with no manifest.json raises BackupError."""
    manager = BackupManager()
    with pytest.raises(BackupError, match="manifest not found"):
        manager.verify(tmp_path / "empty")


def test_verify_raises_when_postgres_file_missing(tmp_path: Path) -> None:
    """A manifest referencing a missing postgres dump file fails verification."""
    _write_manifest(
        tmp_path,
        {"postgres": {"status": "completed", "file": "state_store.pgdump", "sha256": "abc"}},
    )
    manager = BackupManager()
    with pytest.raises(BackupError, match="postgres backup file missing"):
        manager.verify(tmp_path)


def test_verify_raises_when_postgres_digest_mismatch(tmp_path: Path) -> None:
    """A postgres dump whose contents no longer match the manifest digest fails."""
    (tmp_path / "state_store.pgdump").write_bytes(b"actual-bytes")
    _write_manifest(
        tmp_path,
        {
            "postgres": {
                "status": "completed",
                "file": "state_store.pgdump",
                "sha256": "0" * 64,
            }
        },
    )
    manager = BackupManager()
    with pytest.raises(BackupError, match="postgres digest mismatch"):
        manager.verify(tmp_path)


def test_verify_raises_when_artifact_file_missing(tmp_path: Path) -> None:
    """A manifest referencing a missing mirrored artifact file fails verification."""
    _write_manifest(
        tmp_path,
        {
            "artifacts": {
                "status": "completed",
                "entries": [
                    {
                        "bucket": "logs",
                        "object_key": "a.log",
                        "sha256": "abc",
                        "file": "artifacts/logs/a.log",
                    }
                ],
            }
        },
    )
    manager = BackupManager()
    with pytest.raises(BackupError, match="artifact file missing"):
        manager.verify(tmp_path)


def test_verify_raises_when_artifact_digest_mismatch(tmp_path: Path) -> None:
    """A mirrored artifact whose bytes no longer match its digest fails verification."""
    artifact_path = tmp_path / "artifacts" / "logs" / "a.log"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"tampered")
    _write_manifest(
        tmp_path,
        {
            "artifacts": {
                "status": "completed",
                "entries": [
                    {
                        "bucket": "logs",
                        "object_key": "a.log",
                        "sha256": "0" * 64,
                        "file": "artifacts/logs/a.log",
                    }
                ],
            }
        },
    )
    manager = BackupManager()
    with pytest.raises(BackupError, match="artifact digest mismatch"):
        manager.verify(tmp_path)


def test_verify_ignores_skipped_components(tmp_path: Path) -> None:
    """Components recorded as skipped are not checked for files or digests."""
    _write_manifest(
        tmp_path,
        {
            "sqlite": {"status": "skipped"},
            "postgres": {"status": "skipped"},
            "artifacts": {"status": "skipped"},
        },
    )
    manager = BackupManager()
    manifest = manager.verify(tmp_path)
    assert manifest["components"]["postgres"]["status"] == "skipped"


# _backup_artifacts / _restore_artifacts / _iter_object_keys


def test_backup_artifacts_skipped_when_no_store_configured(tmp_path: Path) -> None:
    """With no artifact store configured, the artifacts component is skipped."""
    manager = BackupManager(database_url="sqlite:///x.db")
    result = manager._backup_artifacts(tmp_path, {"components": {}})
    assert result.status == "skipped"
    assert "no artifact store" in result.detail


def test_restore_artifacts_skipped_when_not_in_backup(tmp_path: Path) -> None:
    """An empty component spec (absent from the manifest) skips restore."""
    manager = BackupManager()
    result = manager._restore_artifacts(tmp_path, {})
    assert result == ComponentResult("artifacts", "skipped", "not in backup")


def test_restore_artifacts_raises_when_no_store_configured(tmp_path: Path) -> None:
    """A backup that contains artifacts cannot be restored without a target store."""
    manager = BackupManager(artifact_store=None)
    spec = {
        "status": "completed",
        "entries": [
            {
                "bucket": "logs",
                "object_key": "a.log",
                "kind": "log",
                "sha256": "0" * 64,
                "file": "artifacts/logs/a.log",
            }
        ],
    }
    with pytest.raises(BackupError, match="no artifact store is configured"):
        manager._restore_artifacts(tmp_path, spec)


def test_restore_artifacts_raises_on_digest_mismatch(tmp_path: Path) -> None:
    """A manifest entry whose recorded digest disagrees with the re-uploaded payload fails.

    This exercises the defensive re-check inside ``_restore_artifacts`` itself
    (independent of ``verify()``, which is bypassed here by calling the
    private method directly with a manifest entry whose digest was corrupted
    after being written, while the underlying file content is untouched).
    """
    artifact_path = tmp_path / "artifacts" / "logs" / "a.log"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"real-bytes")
    store = LocalArtifactStore(tmp_path / "restored")
    manager = BackupManager(artifact_store=store)
    spec = {
        "status": "completed",
        "entries": [
            {
                "bucket": "logs",
                "object_key": "a.log",
                "kind": "log",
                "sha256": "0" * 64,
                "file": "artifacts/logs/a.log",
            }
        ],
    }
    with pytest.raises(BackupError, match="restored artifact digest mismatch"):
        manager._restore_artifacts(tmp_path, spec)


def test_iter_object_keys_raises_for_unsupported_store_type() -> None:
    """Enumerating keys of a store that is neither Local nor MinIO raises BackupError."""

    class _OtherStore(ArtifactStore):
        def put_artifact(self, kind: Any, object_key: str, payload: bytes, *, content_type: str = "") -> Any:
            raise NotImplementedError

        def get_artifact(self, bucket: str, object_key: str) -> bytes:
            raise NotImplementedError

    with pytest.raises(BackupError, match="artifact enumeration not supported"):
        list(BackupManager._iter_object_keys(_OtherStore()))


def test_backup_artifacts_enumerates_only_files_under_bucket(tmp_path: Path) -> None:
    """Backing up artifacts mirrors only files, skipping empty bucket directories."""
    store = LocalArtifactStore(tmp_path / "store")
    store.put_artifact(ArtifactKind.LOG, "a/b.log", b"payload")
    manager = BackupManager(artifact_store=store)
    manifest: dict[str, Any] = {"components": {}}
    result = manager._backup_artifacts(tmp_path / "out", manifest)
    assert result.status == "completed"
    assert manifest["components"]["artifacts"]["count"] == 1
    assert manifest["components"]["artifacts"]["entries"][0]["object_key"] == "a/b.log"


# BackupReport


def test_backup_report_skipped_property_filters_by_status(tmp_path: Path) -> None:
    """``BackupReport.skipped`` returns only the components marked skipped."""
    report = BackupReport(
        backup_dir=tmp_path,
        components=(
            ComponentResult("sqlite", "completed"),
            ComponentResult("postgres", "skipped", "no tooling"),
            ComponentResult("artifacts", "skipped", "no store"),
        ),
    )
    assert [c.name for c in report.skipped] == ["postgres", "artifacts"]


# main() CLI


class _FakeSettings:
    """Stand-in for :class:`backend.config.settings.Settings` used by ``main()``."""

    def __init__(
        self,
        database_url: str,
        *,
        backup_status_path: str = "",
        backup_database_url: str = "",
    ) -> None:
        self.database_url = database_url
        self.autodev_backup_status_path = backup_status_path
        self.autodev_backup_database_url = backup_database_url


def test_main_backup_command_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main(["backup", ...])`` drives a real backup and prints component statuses."""
    db_path = tmp_path / "state.db"
    _make_sqlite_db(db_path)
    store = LocalArtifactStore(tmp_path / "artifacts")
    status_path = tmp_path / "backup-status.json"
    monkeypatch.setattr(
        "backend.config.settings.get_settings",
        lambda: _FakeSettings(
            f"sqlite:///{db_path}", backup_status_path=str(status_path)
        ),
    )
    monkeypatch.setattr("backend.artifacts.store.get_artifact_store", lambda settings: store)

    exit_code = main(["backup", "--out", str(tmp_path / "out")])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "sqlite: completed" in out
    assert (tmp_path / "out" / MANIFEST_FILENAME).is_file()

    status = BackupStatusStore(status_path).read()
    assert status is not None
    assert status.last_result == "success"
    assert status.last_duration_seconds is not None
    assert status.last_duration_seconds >= 0


def test_main_restore_command_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main(["restore", ...])`` drives a real restore from a previously written backup."""
    db_path = tmp_path / "state.db"
    _make_sqlite_db(db_path)
    store = LocalArtifactStore(tmp_path / "artifacts")
    settings = _FakeSettings(
        f"sqlite:///{db_path}",
        backup_status_path=str(tmp_path / "backup-status.json"),
    )
    monkeypatch.setattr("backend.config.settings.get_settings", lambda: settings)
    monkeypatch.setattr("backend.artifacts.store.get_artifact_store", lambda s: store)
    BackupManager(database_url=settings.database_url, artifact_store=store).backup(
        tmp_path / "out"
    )

    exit_code = main(["restore", "--from", str(tmp_path / "out")])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "sqlite: completed" in out


def test_main_returns_1_and_prints_error_on_backup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main()`` reports a non-zero exit and an ``error:`` line on ``BackupError``."""
    status_path = tmp_path / "backup-status.json"
    monkeypatch.setattr(
        "backend.config.settings.get_settings",
        lambda: _FakeSettings(
            f"sqlite:///{tmp_path / 'missing.db'}",
            backup_status_path=str(status_path),
        ),
    )
    monkeypatch.setattr(
        "backend.artifacts.store.get_artifact_store", lambda settings: None
    )

    exit_code = main(["backup", "--out", str(tmp_path / "out")])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_main_records_backup_failure_in_status_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failed configured backup is durably recorded as a failure, not silently lost."""
    status_path = tmp_path / "backup-status.json"
    monkeypatch.setattr(
        "backend.config.settings.get_settings",
        lambda: _FakeSettings(
            f"sqlite:///{tmp_path / 'missing.db'}",
            backup_status_path=str(status_path),
        ),
    )
    monkeypatch.setattr(
        "backend.artifacts.store.get_artifact_store", lambda settings: None
    )

    exit_code = main(["backup", "--out", str(tmp_path / "out")])

    assert exit_code == 1
    status = BackupStatusStore(status_path).read()
    assert status is not None
    assert status.last_result == "failure"
    assert status.consecutive_failures == 1
    assert status.last_duration_seconds is not None


def test_main_verify_command_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``main(["verify", ...])`` only reads the manifest and needs no artifact store."""
    db_path = tmp_path / "state.db"
    _make_sqlite_db(db_path)
    manager = BackupManager(database_url=f"sqlite:///{db_path}")
    manager.backup(tmp_path / "out")
    monkeypatch.setattr(
        "backend.config.settings.get_settings",
        lambda: _FakeSettings(
            f"sqlite:///{db_path}",
            backup_status_path=str(tmp_path / "backup-status.json"),
        ),
    )

    assert main(["verify", "--from", str(tmp_path / "out")]) == 0
