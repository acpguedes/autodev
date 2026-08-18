"""Upgrade path & version compatibility (E34-S3).

``autodev upgrade`` orchestrates a versioned upgrade of the state store:
back up first, reusing the E8-S4 :class:`~backend.persistence.backup.BackupManager`
contract, then trigger the migration runner's compatibility check
(E34-S3-T1, :class:`~backend.persistence.migrations.SchemaVersionMismatchError`)
by constructing the configured store. Rollback posture reuses the same
backup/restore machinery rather than a bespoke mechanism — see
``docs/execution/upgrade.md`` and
``docs/v2_platform/runbooks/e8_restore_runbook.md`` (E34-S3-T2). Release
notes for the target version are a best-effort ``CHANGELOG.md`` lookup, kept
deliberately small as groundwork for the GA v1->v2 upgrade requirement
(E13, E34-S3-T3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend.persistence.backup import BackupManager
from backend.persistence.migrations import SchemaVersionMismatchError

UpgradeStatus = Literal["ok", "refused", "backup_failed"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHANGELOG_PATH = _REPO_ROOT / "CHANGELOG.md"
_VERSION_HEADING = re.compile(r"^##\s*\[?([^\]\s]+)\]?")


@dataclass(frozen=True)
class UpgradeResult:
    """Outcome of an ``autodev upgrade`` attempt.

    Attributes:
        status: ``"ok"`` on success; ``"refused"`` when the E34-S3-T1
            compatibility check blocked the upgrade (the database's
            recorded schema is newer than this install's code knows);
            ``"backup_failed"`` when the pre-migrate backup itself failed —
            in that case no migration was ever attempted.
        detail: Human-readable explanation.
        backup_dir: Where the pre-upgrade backup was written, once a backup
            attempt started (present even on refusal, since the backup ran
            before the compatibility check).
        release_notes: Best-effort ``CHANGELOG.md`` excerpt for the target
            version, or ``""`` when not requested or not found.
    """

    status: UpgradeStatus
    detail: str
    backup_dir: str = ""
    release_notes: str = ""

    def as_dict(self) -> dict[str, str]:
        """Return this result as a JSON-serializable dict."""
        return {
            "status": self.status,
            "detail": self.detail,
            "backup_dir": self.backup_dir,
            "release_notes": self.release_notes,
        }


def _release_notes_for(target_version: str | None) -> str:
    """Return the ``CHANGELOG.md`` section for *target_version*'s heading, if found."""
    if not target_version or not _CHANGELOG_PATH.exists():
        return ""
    lines = _CHANGELOG_PATH.read_text(encoding="utf-8").splitlines()
    start: int | None = None
    for idx, line in enumerate(lines):
        match = _VERSION_HEADING.match(line)
        if match and target_version in match.group(1):
            start = idx
            break
    if start is None:
        return ""
    end = start + 1
    while end < len(lines) and not _VERSION_HEADING.match(lines[end]):
        end += 1
    return "\n".join(lines[start:end]).strip()


def run_upgrade(backup_dir: str | Path, target_version: str | None = None) -> UpgradeResult:
    """Back up the configured state store, then attempt to migrate it.

    Args:
        backup_dir: Directory to write the pre-upgrade backup into (E8-S4
            ``BackupManager`` contract).
        target_version: Optional version label to look up release notes for
            in ``CHANGELOG.md``.

    Returns:
        The upgrade outcome. The backup always runs before any migration is
        attempted, per the story's DoD.
    """
    from backend.config.settings import get_settings

    settings = get_settings()

    artifact_store = None
    try:
        from backend.artifacts import get_artifact_store

        artifact_store = get_artifact_store()
    except Exception:  # noqa: BLE001 - artifact backup is best-effort, matching BackupManager's own posture
        artifact_store = None

    manager = BackupManager(database_url=settings.database_url, artifact_store=artifact_store)
    try:
        report = manager.backup(backup_dir)
    except Exception as exc:  # noqa: BLE001 - any backup failure blocks the migrate attempt entirely
        return UpgradeResult(status="backup_failed", detail=str(exc))

    from backend.persistence.database import get_store, reset_store_cache

    reset_store_cache()
    try:
        get_store()
    except SchemaVersionMismatchError as exc:
        return UpgradeResult(status="refused", detail=str(exc), backup_dir=str(report.backup_dir))

    return UpgradeResult(
        status="ok",
        detail="migrations applied (or already up to date)",
        backup_dir=str(report.backup_dir),
        release_notes=_release_notes_for(target_version),
    )


__all__ = ["UpgradeResult", "UpgradeStatus", "run_upgrade"]
