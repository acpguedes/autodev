"""Tests for the durable backup-health status store (E11-S4)."""

from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path

from backend.persistence.backup_status import BackupStatus, BackupStatusStore


def test_read_returns_none_when_no_status_file(tmp_path: Path) -> None:
    """No status file yet reads as no status, not an error."""
    store = BackupStatusStore(tmp_path / "backup-status.json")

    assert store.read() is None


def test_record_first_success(tmp_path: Path) -> None:
    """The first-ever recorded attempt, a success, has zero consecutive failures."""
    store = BackupStatusStore(tmp_path / "backup-status.json")
    moment = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)

    status = store.record(success=True, occurred_at=moment)

    assert status == BackupStatus(
        last_attempt_timestamp=moment.timestamp(),
        last_success_timestamp=moment.timestamp(),
        consecutive_failures=0,
        last_result="success",
        last_duration_seconds=None,
    )
    assert store.read() == status


def test_record_persists_duration(tmp_path: Path) -> None:
    """A timed attempt's duration round-trips through read() (E59-S3-T2)."""
    store = BackupStatusStore(tmp_path / "backup-status.json")

    status = store.record(success=True, duration_seconds=1.5)

    assert status.last_duration_seconds == 1.5
    read_back = store.read()
    assert read_back is not None
    assert read_back.last_duration_seconds == 1.5


def test_record_failure_preserves_previous_success_timestamp(tmp_path: Path) -> None:
    """A failure after a success keeps the prior success timestamp intact."""
    store = BackupStatusStore(tmp_path / "backup-status.json")
    success_at = datetime(2026, 8, 15, 9, 0, 0, tzinfo=timezone.utc)
    failure_at = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
    store.record(success=True, occurred_at=success_at)

    status = store.record(success=False, occurred_at=failure_at)

    assert status.last_success_timestamp == success_at.timestamp()
    assert status.last_attempt_timestamp == failure_at.timestamp()
    assert status.last_result == "failure"


def test_record_consecutive_failures_increment(tmp_path: Path) -> None:
    """Repeated failures increment the consecutive-failure counter."""
    store = BackupStatusStore(tmp_path / "backup-status.json")

    store.record(success=False)
    store.record(success=False)
    status = store.record(success=False)

    assert status.consecutive_failures == 3


def test_record_success_resets_consecutive_failures(tmp_path: Path) -> None:
    """A success after failures resets the consecutive-failure counter to zero."""
    store = BackupStatusStore(tmp_path / "backup-status.json")
    store.record(success=False)
    store.record(success=False)

    status = store.record(success=True)

    assert status.consecutive_failures == 0
    assert status.last_result == "success"


def test_status_file_has_owner_only_permissions(tmp_path: Path) -> None:
    """The persisted status file is not readable by group or other."""
    path = tmp_path / "backup-status.json"
    store = BackupStatusStore(path)

    store.record(success=True)

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_repeated_writes_produce_valid_atomic_json(tmp_path: Path) -> None:
    """Many sequential writes always leave behind one complete, valid JSON file."""
    path = tmp_path / "backup-status.json"
    store = BackupStatusStore(path)

    for index in range(10):
        store.record(success=index % 2 == 0)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {
        "last_attempt_timestamp",
        "last_success_timestamp",
        "consecutive_failures",
        "last_result",
        "last_duration_seconds",
    }


def test_no_temporary_files_leak_after_repeated_writes(tmp_path: Path) -> None:
    """No stray `.backup-status.json.*` temp files remain after writes."""
    path = tmp_path / "backup-status.json"
    store = BackupStatusStore(path)

    for _ in range(5):
        store.record(success=True)

    leftovers = [p for p in tmp_path.iterdir() if p.name != "backup-status.json"]
    assert leftovers == []


def test_persisted_status_contains_no_exception_text_or_secret_material(
    tmp_path: Path,
) -> None:
    """The persisted record is exactly the four sanitized fields, nothing else."""
    path = tmp_path / "backup-status.json"
    store = BackupStatusStore(path)

    store.record(success=False)

    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert set(data) == {
        "last_attempt_timestamp",
        "last_success_timestamp",
        "consecutive_failures",
        "last_result",
        "last_duration_seconds",
    }
    assert "Error" not in raw
    assert "Traceback" not in raw
