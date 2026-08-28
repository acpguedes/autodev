"""Durable, atomic backup-health status persistence (E11-S4).

Only sanitized, non-secret outcome data is ever persisted here: timestamps,
a failure count, and a result label. Exception text, connection strings, and
any other detail that could carry credentials never reaches this file.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class BackupStatus:
    """Sanitized outcome of the most recent backup attempt.

    Attributes:
        last_attempt_timestamp: Unix timestamp of the most recent attempt.
        last_success_timestamp: Unix timestamp of the most recent success, or
            ``None`` if no attempt has ever succeeded.
        consecutive_failures: Number of failed attempts since the last
            success (or since records began).
        last_result: Outcome of the most recent attempt.
    """

    last_attempt_timestamp: float
    last_success_timestamp: float | None
    consecutive_failures: int
    last_result: Literal["success", "failure"]
    #: Wall-clock duration of the most recent attempt, in seconds. Feeds the
    #: RPO worst-case-data-loss-window calculation (schedule interval +
    #: backup duration, E59-S3-T2) with a measured number instead of an
    #: assumption; ``None`` for records written before this field existed.
    last_duration_seconds: float | None = None


class BackupStatusStore:
    """Reads and atomically writes one durable :class:`BackupStatus` record."""

    def __init__(self, path: Path) -> None:
        """Initialize a durable, local backup-status store.

        Args:
            path: File the status record is persisted to.
        """
        self._path = Path(path)

    def read(self) -> BackupStatus | None:
        """Read the latest backup status.

        Returns:
            The last recorded status, or ``None`` if no status has ever been
            recorded or the file is missing/corrupt.
        """
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
            return BackupStatus(
                last_attempt_timestamp=float(data["last_attempt_timestamp"]),
                last_success_timestamp=(
                    float(data["last_success_timestamp"])
                    if data.get("last_success_timestamp") is not None
                    else None
                ),
                consecutive_failures=int(data["consecutive_failures"]),
                last_result=data["last_result"],
                last_duration_seconds=(
                    float(data["last_duration_seconds"])
                    if data.get("last_duration_seconds") is not None
                    else None
                ),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def record(
        self,
        *,
        success: bool,
        occurred_at: datetime | None = None,
        duration_seconds: float | None = None,
    ) -> BackupStatus:
        """Atomically record a sanitized backup outcome.

        Args:
            success: Whether the backup attempt succeeded.
            occurred_at: When the attempt occurred; defaults to now (UTC).
            duration_seconds: Wall-clock duration of the attempt, if timed.

        Returns:
            The newly persisted status.
        """
        moment = occurred_at or datetime.now(timezone.utc)
        timestamp = moment.timestamp()
        previous = self.read()
        if success:
            status = BackupStatus(
                last_attempt_timestamp=timestamp,
                last_success_timestamp=timestamp,
                consecutive_failures=0,
                last_result="success",
                last_duration_seconds=duration_seconds,
            )
        else:
            status = BackupStatus(
                last_attempt_timestamp=timestamp,
                last_success_timestamp=(
                    previous.last_success_timestamp if previous else None
                ),
                consecutive_failures=(
                    previous.consecutive_failures + 1 if previous else 1
                ),
                last_result="failure",
                last_duration_seconds=duration_seconds,
            )
        self._write(status)
        return status

    def _write(self, status: BackupStatus) -> None:
        """Atomically write one status record with owner-only permissions.

        Args:
            status: Status record to persist.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(status), handle, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, self._path)
            os.chmod(self._path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["BackupStatus", "BackupStatusStore"]
