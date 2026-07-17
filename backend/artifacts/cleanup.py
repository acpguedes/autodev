"""Lifecycle cleanup for artifact store objects (E8-S3/T4).

Two sweep strategies are provided:

- :func:`cleanup_unreferenced_artifacts` — the authoritative, reference-based
  garbage collector. With the durable pointer registry landed (E8-S3/T2,
  :class:`backend.artifacts.pointers.ArtifactPointerStore`), an object is
  garbage exactly when no ``artifacts`` row references its key. An age guard
  (``autodev_artifact_retention_days``) still protects very recent objects,
  since a payload may be written moments before its pointer row commits.
- :func:`cleanup_orphaned_artifacts` — the older best-effort, convention-based
  sweep (age plus caller-supplied allowlist). Kept for callers without access
  to the pointer registry; prefer the reference-based GC.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.artifacts.pointers import ArtifactPointerStore
from backend.artifacts.store import (
    ArtifactStore,
    LocalArtifactStore,
    MinioArtifactStore,
    all_bucket_names,
)
from backend.config.settings import get_settings


@dataclass(frozen=True)
class ArtifactObjectInfo:
    """Metadata about a single stored object, as needed for lifecycle cleanup.

    Attributes:
        bucket: Bucket the object lives in.
        object_key: Relative object key within the bucket.
        size_bytes: Size of the object, in bytes.
        last_modified: Timestamp the object was last written, in UTC.
    """

    bucket: str
    object_key: str
    size_bytes: int
    last_modified: datetime


@dataclass(frozen=True)
class CleanupResult:
    """Outcome of a single orphan-cleanup sweep.

    Attributes:
        removed: Objects that were deleted, or would be under a dry run.
        scanned_count: Total number of objects examined across all buckets.
        dry_run: Whether ``removed`` objects were only reported, not deleted.
    """

    removed: list[ArtifactObjectInfo]
    scanned_count: int
    dry_run: bool


def _iter_local_objects(store: LocalArtifactStore, bucket: str) -> Iterator[ArtifactObjectInfo]:
    """Enumerate stored objects in one bucket of a local filesystem store.

    Args:
        store: The local artifact store to scan.
        bucket: Bucket (subdirectory) to enumerate.

    Yields:
        Metadata for each file found under ``bucket``.
    """
    bucket_root = (store.root / bucket).resolve()
    if not bucket_root.is_dir():
        return
    for path in bucket_root.rglob("*"):
        if not path.is_file():
            continue
        object_key = path.resolve().relative_to(bucket_root).as_posix()
        stat = path.stat()
        yield ArtifactObjectInfo(
            bucket=bucket,
            object_key=object_key,
            size_bytes=stat.st_size,
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )


def _iter_minio_objects(store: MinioArtifactStore, bucket: str) -> Iterator[ArtifactObjectInfo]:
    """Enumerate stored objects in one bucket of a MinIO-backed store.

    Args:
        store: The MinIO artifact store to scan.
        bucket: Bucket to enumerate.

    Yields:
        Metadata for each object found in ``bucket``.
    """
    for obj in store.client.list_objects(bucket, recursive=True):
        if obj.is_dir or obj.object_name is None:
            continue
        yield ArtifactObjectInfo(
            bucket=bucket,
            object_key=obj.object_name,
            size_bytes=obj.size or 0,
            last_modified=obj.last_modified or datetime.now(timezone.utc),
        )


def iter_all_objects(store: ArtifactStore) -> Iterator[ArtifactObjectInfo]:
    """Enumerate every object across all artifact buckets for a store.

    Args:
        store: The artifact store to scan. Must be a
            :class:`~backend.artifacts.store.LocalArtifactStore` or
            :class:`~backend.artifacts.store.MinioArtifactStore`.

    Yields:
        Metadata for each stored object, across all known buckets.

    Raises:
        TypeError: If ``store`` is a backend this function does not know how
            to enumerate.
    """
    for bucket in all_bucket_names():
        if isinstance(store, LocalArtifactStore):
            yield from _iter_local_objects(store, bucket)
        elif isinstance(store, MinioArtifactStore):
            yield from _iter_minio_objects(store, bucket)
        else:
            raise TypeError(f"Cannot enumerate objects for store type {type(store).__name__}")


def _delete_object(store: ArtifactStore, bucket: str, object_key: str) -> None:
    """Delete a single object from the given store's backend.

    Args:
        store: The artifact store the object lives in.
        bucket: Bucket the object lives in.
        object_key: Relative object key within the bucket.

    Raises:
        TypeError: If ``store`` is a backend this function does not know how
            to delete from.
    """
    if isinstance(store, LocalArtifactStore):
        target = (store.root / bucket / object_key).resolve()
        target.unlink(missing_ok=True)
    elif isinstance(store, MinioArtifactStore):
        store.client.remove_object(bucket, object_key)
    else:
        raise TypeError(f"Cannot delete objects for store type {type(store).__name__}")


def cleanup_orphaned_artifacts(
    store: ArtifactStore,
    *,
    older_than: timedelta = timedelta(days=7),
    referenced_object_keys: Collection[str] | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupResult:
    """Sweep an artifact store for orphaned objects and remove them.

    See the module docstring for the important caveat: without a State
    Store table of artifact references (E8-S3/T2), this is a best-effort,
    age- and allowlist-based heuristic, not a true reference-counted
    garbage collector.

    Args:
        store: The artifact store to sweep.
        older_than: Minimum age an object must have before it is eligible
            for removal. Defaults to 7 days.
        referenced_object_keys: Object keys known to still be referenced;
            these are never removed regardless of age. Defaults to none.
        dry_run: If ``True``, compute and return what would be removed
            without deleting anything.
        now: Reference timestamp used to compute object age; defaults to
            the current UTC time. Exposed for deterministic testing.

    Returns:
        A :class:`CleanupResult` describing what was (or would be) removed.
    """
    reference = now or datetime.now(timezone.utc)
    referenced = set(referenced_object_keys or ())
    removed: list[ArtifactObjectInfo] = []
    scanned_count = 0

    for info in iter_all_objects(store):
        scanned_count += 1
        if info.object_key in referenced:
            continue
        age = reference - info.last_modified
        if age < older_than:
            continue
        removed.append(info)
        if not dry_run:
            _delete_object(store, info.bucket, info.object_key)

    return CleanupResult(removed=removed, scanned_count=scanned_count, dry_run=dry_run)


def cleanup_unreferenced_artifacts(
    store: ArtifactStore,
    pointers: ArtifactPointerStore | None = None,
    *,
    retention_days: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupResult:
    """Garbage-collect stored objects no pointer row references (E8-S3/T4).

    Authoritative, reference-counted cleanup: every object key present in the
    ``artifacts`` State Store table (any tenant) is kept; everything else is
    garbage, subject to an age guard so payloads written moments before their
    pointer row commits are never swept.

    Args:
        store: The artifact store to sweep.
        pointers: Pointer registry to consult; defaults to a store built via
            :class:`~backend.artifacts.pointers.ArtifactPointerStore`.
        retention_days: Minimum age, in days, an unreferenced object must
            have before removal. Defaults to the
            ``autodev_artifact_retention_days`` setting. ``-1`` disables
            collection entirely (objects are kept forever).
        dry_run: If ``True``, compute and return what would be removed
            without deleting anything.
        now: Reference timestamp used to compute object age; defaults to
            the current UTC time. Exposed for deterministic testing.

    Returns:
        A :class:`CleanupResult` describing what was (or would be) removed.
    """
    days = retention_days if retention_days is not None else get_settings().autodev_artifact_retention_days
    if days < 0:
        return CleanupResult(removed=[], scanned_count=0, dry_run=dry_run)
    registry = pointers or ArtifactPointerStore()
    return cleanup_orphaned_artifacts(
        store,
        older_than=timedelta(days=days),
        referenced_object_keys=registry.referenced_object_keys(),
        dry_run=dry_run,
        now=now,
    )


__all__ = [
    "ArtifactObjectInfo",
    "CleanupResult",
    "cleanup_orphaned_artifacts",
    "cleanup_unreferenced_artifacts",
    "iter_all_objects",
]
