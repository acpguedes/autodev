"""Backup, restore, and reversibility tooling for the persistence layer (E8-S4).

This module provides :class:`BackupManager`, which produces self-describing
backup directories covering the three durable components of the platform:

* **SQLite State Store** — backed up with the online backup API
  (:meth:`sqlite3.Connection.backup`), so a consistent snapshot is taken even
  while other connections are writing.
* **PostgreSQL State Store** — thin wrappers around ``pg_dump`` /
  ``pg_restore``. When the tooling or a PostgreSQL ``DATABASE_URL`` is not
  available the component is recorded as ``skipped`` rather than failing, so
  local-first deployments can still take SQLite + artifact backups.
* **Artifact Store** — objects are mirrored **only through the public
  artifact-store API** (:func:`backend.artifacts.store.all_bucket_names`,
  :meth:`~backend.artifacts.store.ArtifactStore.get_artifact`,
  :meth:`~backend.artifacts.store.ArtifactStore.put_artifact`, and the public
  ``root`` / ``client`` attributes used solely for key enumeration). Backup
  code never touches bucket internals directly.

Every backup directory contains a ``manifest.json`` with a ``schema_version``
and a SHA-256 digest per copied file, enabling integrity verification before
any restore (see ``docs/v2_platform/runbooks/e8_restore_runbook.md``).

CLI usage (exits non-zero on any failure)::

    python -m backend.persistence.backup backup --out <dir>
    python -m backend.persistence.backup restore --from <dir>
    python -m backend.persistence.backup verify --from <dir>
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Iterable, Sequence

from backend.artifacts.store import (
    ArtifactKind,
    ArtifactStore,
    LocalArtifactStore,
    MinioArtifactStore,
    all_bucket_names,
)

#: Version of the backup manifest layout. Bump on breaking layout changes.
MANIFEST_SCHEMA_VERSION = 1

#: File name of the manifest written at the root of every backup directory.
MANIFEST_FILENAME = "manifest.json"

#: Sub-directory of a backup dir holding mirrored artifact payloads.
ARTIFACTS_SUBDIR = "artifacts"

#: File name of the SQLite snapshot inside a backup directory.
SQLITE_SNAPSHOT_FILENAME = "state_store.sqlite3"

#: File name of the PostgreSQL logical dump inside a backup directory.
POSTGRES_DUMP_FILENAME = "state_store.pgdump"

#: Mapping of bucket name -> artifact kind, derived exclusively from the
#: public artifact-store API: ``ArtifactKind`` iterates in declaration order
#: and :func:`all_bucket_names` returns the backing buckets in the same
#: declaration order, so pairing them positionally is stable.
_BUCKET_TO_KIND: dict[str, ArtifactKind] = dict(
    zip(all_bucket_names(), ArtifactKind)
)


class BackupError(RuntimeError):
    """Raised when a backup, verify, or restore step fails."""


def _sha256_file(path: Path) -> str:
    """Compute the hex-encoded SHA-256 digest of a file.

    Args:
        path: File to hash.

    Returns:
        The hex-encoded SHA-256 digest of the file contents.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Returns:
        Current UTC timestamp with second precision, e.g.
        ``2026-07-17T12:00:00+00:00``.
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )


@dataclass(frozen=True)
class ComponentResult:
    """Outcome of backing up or restoring one component.

    Attributes:
        name: Component identifier (``sqlite``, ``postgres``, ``artifacts``).
        status: ``completed`` or ``skipped``.
        detail: Human-readable explanation (mainly for ``skipped``).
    """

    name: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class BackupReport:
    """Aggregate outcome of a backup or restore invocation.

    Attributes:
        backup_dir: Directory the backup was written to / read from.
        components: Per-component outcomes.
    """

    backup_dir: Path
    components: tuple[ComponentResult, ...] = field(default_factory=tuple)

    @property
    def skipped(self) -> tuple[ComponentResult, ...]:
        """Return the components that were skipped.

        Returns:
            All component results whose status is ``skipped``.
        """
        return tuple(c for c in self.components if c.status == "skipped")


class BackupManager:
    """Coordinates backup and restore of SQLite, PostgreSQL, and artifacts.

    Args:
        database_url: ``DATABASE_URL`` of the State Store. ``sqlite://`` URLs
            enable the SQLite component; ``postgresql://`` / ``postgres://``
            URLs enable the PostgreSQL component.
        artifact_store: Artifact store whose objects should be mirrored, or
            ``None`` to skip the artifact component.
    """

    def __init__(
        self,
        database_url: str = "",
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.database_url = (database_url or "").strip()
        self.artifact_store = artifact_store

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def backup(self, backup_dir: str | Path) -> BackupReport:
        """Write a full backup (SQLite, PostgreSQL, artifacts) with manifest.

        Args:
            backup_dir: Directory to create the backup in (created if needed).

        Returns:
            A report describing which components completed or were skipped.

        Raises:
            BackupError: If any enabled component fails to back up.
        """
        target = Path(backup_dir).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)

        components: list[ComponentResult] = []
        manifest: dict[str, Any] = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "created_at": _utcnow_iso(),
            "components": {},
        }

        components.append(self._backup_sqlite(target, manifest))
        components.append(self._backup_postgres(target, manifest))
        components.append(self._backup_artifacts(target, manifest))

        manifest_path = target / MANIFEST_FILENAME
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        return BackupReport(backup_dir=target, components=tuple(components))

    def _backup_sqlite(
        self, target: Path, manifest: dict[str, Any]
    ) -> ComponentResult:
        """Snapshot the SQLite database with the online backup API.

        Args:
            target: Backup directory.
            manifest: Manifest dict updated in place.

        Returns:
            The component result (``completed`` or ``skipped``).

        Raises:
            BackupError: If the SQLite online backup fails.
        """
        if not self.database_url.startswith("sqlite://"):
            manifest["components"]["sqlite"] = {"status": "skipped"}
            return ComponentResult(
                "sqlite", "skipped", "DATABASE_URL is not sqlite://"
            )
        from backend.persistence.sqlite_adapter import _resolve_db_path

        db_path = _resolve_db_path(self.database_url)
        if not db_path.exists():
            raise BackupError(f"SQLite database not found: {db_path}")
        snapshot = target / SQLITE_SNAPSHOT_FILENAME
        try:
            source = sqlite3.connect(db_path)
            try:
                dest = sqlite3.connect(snapshot)
                try:
                    source.backup(dest)
                finally:
                    dest.close()
            finally:
                source.close()
        except sqlite3.Error as exc:  # pragma: no cover - depends on I/O
            raise BackupError(f"SQLite online backup failed: {exc}") from exc
        manifest["components"]["sqlite"] = {
            "status": "completed",
            "file": SQLITE_SNAPSHOT_FILENAME,
            "sha256": _sha256_file(snapshot),
            "size_bytes": snapshot.stat().st_size,
            "source_path": str(db_path),
        }
        return ComponentResult("sqlite", "completed")

    def _backup_postgres(
        self, target: Path, manifest: dict[str, Any]
    ) -> ComponentResult:
        """Dump PostgreSQL with ``pg_dump`` (custom format), if available.

        Args:
            target: Backup directory.
            manifest: Manifest dict updated in place.

        Returns:
            The component result. Skipped when ``DATABASE_URL`` is not
            PostgreSQL or ``pg_dump`` is not on ``PATH``.

        Raises:
            BackupError: If ``pg_dump`` exits non-zero.
        """
        if not (
            self.database_url.startswith("postgresql://")
            or self.database_url.startswith("postgres://")
        ):
            manifest["components"]["postgres"] = {"status": "skipped"}
            return ComponentResult(
                "postgres", "skipped", "DATABASE_URL is not postgresql://"
            )
        if shutil.which("pg_dump") is None:
            manifest["components"]["postgres"] = {"status": "skipped"}
            return ComponentResult(
                "postgres", "skipped", "pg_dump not found on PATH"
            )
        dump_path = target / POSTGRES_DUMP_FILENAME
        result = subprocess.run(
            [
                "pg_dump",
                "--format=custom",
                f"--file={dump_path}",
                self.database_url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise BackupError(f"pg_dump failed: {result.stderr.strip()}")
        manifest["components"]["postgres"] = {
            "status": "completed",
            "file": POSTGRES_DUMP_FILENAME,
            "sha256": _sha256_file(dump_path),
            "size_bytes": dump_path.stat().st_size,
        }
        return ComponentResult("postgres", "completed")

    def _backup_artifacts(
        self, target: Path, manifest: dict[str, Any]
    ) -> ComponentResult:
        """Mirror every artifact through the public artifact-store API.

        Object keys are enumerated via public surface only (the ``root``
        directory of :class:`LocalArtifactStore`, or the public ``client``
        property of :class:`MinioArtifactStore`); payload bytes are read via
        :meth:`~backend.artifacts.store.ArtifactStore.get_artifact`.

        Args:
            target: Backup directory.
            manifest: Manifest dict updated in place.

        Returns:
            The component result. Skipped when no artifact store was given.

        Raises:
            BackupError: If reading any artifact fails.
        """
        store = self.artifact_store
        if store is None:
            manifest["components"]["artifacts"] = {"status": "skipped"}
            return ComponentResult(
                "artifacts", "skipped", "no artifact store configured"
            )
        entries: list[dict[str, Any]] = []
        mirror_root = target / ARTIFACTS_SUBDIR
        for bucket, object_key in self._iter_object_keys(store):
            try:
                payload = store.get_artifact(bucket, object_key)
            except (OSError, ValueError) as exc:
                raise BackupError(
                    f"failed to read artifact {bucket}/{object_key}: {exc}"
                ) from exc
            local_path = mirror_root / bucket / object_key
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(payload)
            entries.append(
                {
                    "bucket": bucket,
                    "object_key": object_key,
                    "kind": str(_BUCKET_TO_KIND[bucket]),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "file": f"{ARTIFACTS_SUBDIR}/{bucket}/{object_key}",
                }
            )
        manifest["components"]["artifacts"] = {
            "status": "completed",
            "count": len(entries),
            "entries": entries,
        }
        return ComponentResult("artifacts", "completed")

    @staticmethod
    def _iter_object_keys(
        store: ArtifactStore,
    ) -> Iterable[tuple[str, str]]:
        """Enumerate ``(bucket, object_key)`` pairs via public surface only.

        Args:
            store: Artifact store to enumerate.

        Yields:
            ``(bucket, object_key)`` for every stored object.

        Raises:
            BackupError: If the store backend does not support enumeration.
        """
        buckets = all_bucket_names()
        if isinstance(store, LocalArtifactStore):
            for bucket in buckets:
                bucket_root = store.root / bucket
                if not bucket_root.is_dir():
                    continue
                for path in sorted(bucket_root.rglob("*")):
                    if path.is_file():
                        yield bucket, path.relative_to(bucket_root).as_posix()
            return
        if isinstance(store, MinioArtifactStore):
            for bucket in buckets:
                if not store.client.bucket_exists(bucket):
                    continue
                for obj in store.client.list_objects(bucket, recursive=True):
                    yield bucket, obj.object_name
            return
        raise BackupError(
            f"artifact enumeration not supported for {type(store).__name__}"
        )

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def verify(self, backup_dir: str | Path) -> dict[str, Any]:
        """Verify manifest integrity (schema version + SHA-256 per file).

        Args:
            backup_dir: Directory containing a previously written backup.

        Returns:
            The parsed, validated manifest.

        Raises:
            BackupError: If the manifest is missing, has an unsupported
                schema version, or any file digest does not match.
        """
        source = Path(backup_dir).expanduser().resolve()
        manifest_path = source / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise BackupError(f"manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = manifest.get("schema_version")
        if version != MANIFEST_SCHEMA_VERSION:
            raise BackupError(
                f"unsupported manifest schema_version: {version!r}"
            )
        components = manifest.get("components", {})
        for name in ("sqlite", "postgres"):
            spec = components.get(name, {})
            if spec.get("status") != "completed":
                continue
            path = source / spec["file"]
            if not path.is_file():
                raise BackupError(f"{name} backup file missing: {path}")
            actual = _sha256_file(path)
            if actual != spec["sha256"]:
                raise BackupError(
                    f"{name} digest mismatch: expected {spec['sha256']}, "
                    f"got {actual}"
                )
        artifacts = components.get("artifacts", {})
        if artifacts.get("status") == "completed":
            for entry in artifacts.get("entries", []):
                path = source / entry["file"]
                if not path.is_file():
                    raise BackupError(f"artifact file missing: {path}")
                actual = _sha256_file(path)
                if actual != entry["sha256"]:
                    raise BackupError(
                        "artifact digest mismatch for "
                        f"{entry['bucket']}/{entry['object_key']}"
                    )
        return manifest

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore(self, backup_dir: str | Path) -> BackupReport:
        """Restore all components recorded in a verified backup directory.

        Args:
            backup_dir: Directory containing a previously written backup.

        Returns:
            A report describing which components were restored or skipped.

        Raises:
            BackupError: If verification fails or any restore step fails.
        """
        source = Path(backup_dir).expanduser().resolve()
        manifest = self.verify(source)
        components = manifest.get("components", {})
        results: list[ComponentResult] = []
        results.append(self._restore_sqlite(source, components.get("sqlite", {})))
        results.append(
            self._restore_postgres(source, components.get("postgres", {}))
        )
        results.append(
            self._restore_artifacts(source, components.get("artifacts", {}))
        )
        return BackupReport(backup_dir=source, components=tuple(results))

    def _restore_sqlite(
        self, source: Path, spec: dict[str, Any]
    ) -> ComponentResult:
        """Restore the SQLite database from its snapshot.

        Args:
            source: Backup directory.
            spec: ``sqlite`` component manifest entry.

        Returns:
            The component result.

        Raises:
            BackupError: If the target URL is not SQLite while a snapshot
                exists, or the online restore fails.
        """
        if spec.get("status") != "completed":
            return ComponentResult("sqlite", "skipped", "not in backup")
        if not self.database_url.startswith("sqlite://"):
            raise BackupError(
                "backup contains a SQLite snapshot but DATABASE_URL is not "
                "sqlite://"
            )
        from backend.persistence.sqlite_adapter import _resolve_db_path

        db_path = _resolve_db_path(self.database_url)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = source / spec["file"]
        try:
            snap_conn = sqlite3.connect(snapshot)
            try:
                dest = sqlite3.connect(db_path)
                try:
                    snap_conn.backup(dest)
                finally:
                    dest.close()
            finally:
                snap_conn.close()
        except sqlite3.Error as exc:  # pragma: no cover - depends on I/O
            raise BackupError(f"SQLite restore failed: {exc}") from exc
        return ComponentResult("sqlite", "completed")

    def _restore_postgres(
        self, source: Path, spec: dict[str, Any]
    ) -> ComponentResult:
        """Restore PostgreSQL from the ``pg_dump`` custom-format dump.

        Args:
            source: Backup directory.
            spec: ``postgres`` component manifest entry.

        Returns:
            The component result. Skipped when the dump is absent or
            ``pg_restore`` is not on ``PATH``.

        Raises:
            BackupError: If ``pg_restore`` exits non-zero.
        """
        if spec.get("status") != "completed":
            return ComponentResult("postgres", "skipped", "not in backup")
        if shutil.which("pg_restore") is None:
            return ComponentResult(
                "postgres", "skipped", "pg_restore not found on PATH"
            )
        if not (
            self.database_url.startswith("postgresql://")
            or self.database_url.startswith("postgres://")
        ):
            raise BackupError(
                "backup contains a PostgreSQL dump but DATABASE_URL is not "
                "postgresql://"
            )
        dump_path = source / spec["file"]
        result = subprocess.run(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                f"--dbname={self.database_url}",
                str(dump_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise BackupError(f"pg_restore failed: {result.stderr.strip()}")
        return ComponentResult("postgres", "completed")

    def _restore_artifacts(
        self, source: Path, spec: dict[str, Any]
    ) -> ComponentResult:
        """Re-upload mirrored artifacts via the public ``put_artifact`` API.

        Args:
            source: Backup directory.
            spec: ``artifacts`` component manifest entry.

        Returns:
            The component result.

        Raises:
            BackupError: If no artifact store is configured while the backup
                contains artifacts, or a re-upload fails integrity checks.
        """
        if spec.get("status") != "completed":
            return ComponentResult("artifacts", "skipped", "not in backup")
        store = self.artifact_store
        if store is None:
            raise BackupError(
                "backup contains artifacts but no artifact store is configured"
            )
        for entry in spec.get("entries", []):
            payload = (source / entry["file"]).read_bytes()
            pointer = store.put_artifact(
                ArtifactKind(entry["kind"]),
                entry["object_key"],
                payload,
            )
            if pointer.sha256 != entry["sha256"]:
                raise BackupError(
                    "restored artifact digest mismatch for "
                    f"{entry['bucket']}/{entry['object_key']}"
                )
        return ComponentResult("artifacts", "completed")


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured ``argparse`` parser with ``backup`` / ``restore`` /
        ``verify`` subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="python -m backend.persistence.backup",
        description="Backup / restore the AutoDev State Store and artifacts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_backup = sub.add_parser("backup", help="write a new backup directory")
    p_backup.add_argument("--out", required=True, help="target directory")
    p_restore = sub.add_parser("restore", help="restore from a backup dir")
    p_restore.add_argument(
        "--from", dest="source", required=True, help="backup directory"
    )
    p_verify = sub.add_parser("verify", help="verify manifest integrity")
    p_verify.add_argument(
        "--from", dest="source", required=True, help="backup directory"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        ``0`` on success; ``1`` on any :class:`BackupError`.
    """
    args = _build_parser().parse_args(argv)
    from backend.artifacts.store import get_artifact_store
    from backend.config.settings import get_settings

    settings = get_settings()
    try:
        if args.command == "verify":
            # Verification only reads the backup directory; it needs neither
            # the database nor the artifact store.
            BackupManager(database_url=settings.database_url).verify(args.source)
            print("manifest OK")
            return 0
        manager = BackupManager(
            database_url=settings.database_url,
            artifact_store=get_artifact_store(settings),
        )
        report = (
            manager.backup(args.out)
            if args.command == "backup"
            else manager.restore(args.source)
        )
        for component in report.components:
            print(f"{component.name}: {component.status} {component.detail}".strip())
    except (BackupError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
