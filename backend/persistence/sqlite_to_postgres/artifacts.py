"""Artifact pointer verification for the E58 migration (E58-S3-T2).

The ``artifacts`` table (:class:`~backend.artifacts.pointers.ArtifactPointerStore`)
is a normal entry in :data:`~backend.persistence.sqlite_to_postgres.tables.TABLE_COPY_ORDER`
and its rows are copied like any other table by
:func:`~backend.persistence.sqlite_to_postgres.copy.copy_all_tables`. What is
specific to artifacts is verifying, after that copy, that each pointer's
referenced object still resolves in the *currently configured* object store
-- the payload bytes themselves are never copied by this migrator (they live
outside either database, per ADR-026's scope). A pointer whose object cannot
be found is reported, not silently dropped: it already migrated as a row (so
source/destination row counts still reconcile, ADR-026 decision 9), and the
operator decides what to do with a stale reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.artifacts.store import ArtifactStore, LocalArtifactStore, MinioArtifactStore


@dataclass(frozen=True)
class DanglingArtifactPointer:
    """A migrated artifact pointer whose referenced object does not resolve.

    Attributes:
        bucket: Bucket the pointer names.
        object_key: Object key the pointer names.
        tenant_id: Tenant the pointer's row belongs to.
    """

    bucket: str
    object_key: str
    tenant_id: str


def _object_exists(store: ArtifactStore, bucket: str, object_key: str) -> bool:
    """Whether an object resolves in *store*, without reading its payload.

    Args:
        store: Artifact store to check against.
        bucket: Bucket name.
        object_key: Object key within the bucket.

    Returns:
        ``True`` if the object exists.

    Raises:
        ValueError: If *store*'s backend is not one this function knows how
            to check without a full read (mirrors
            :meth:`backend.persistence.backup.BackupManager._iter_object_keys`'s
            same posture: public surface only, an unsupported backend is an
            explicit error, not a guess).
    """
    if isinstance(store, LocalArtifactStore):
        return (store.root / bucket / object_key).is_file()
    if isinstance(store, MinioArtifactStore):
        try:
            store.client.stat_object(bucket, object_key)
        except Exception:  # noqa: BLE001 - the minio client raises a backend-specific S3Error
            return False
        return True
    raise ValueError(f"artifact existence check not supported for {type(store).__name__}")


def find_dangling_artifact_pointers(
    dest_conn: Any, artifact_store: ArtifactStore
) -> tuple[DanglingArtifactPointer, ...]:
    """Find every migrated artifact pointer whose object does not resolve.

    Args:
        dest_conn: Open destination psycopg connection, after the
            ``artifacts`` table has been copied.
        artifact_store: The currently configured artifact store to check
            pointers against.

    Returns:
        Dangling pointers, if any. An empty result means every migrated
        pointer resolves.
    """
    rows = dest_conn.execute(
        "SELECT bucket, object_key, tenant_id FROM artifacts"
    ).fetchall()
    dangling = []
    for bucket, object_key, tenant_id in rows:
        if not _object_exists(artifact_store, bucket, object_key):
            dangling.append(
                DanglingArtifactPointer(bucket=bucket, object_key=object_key, tenant_id=tenant_id)
            )
    return tuple(dangling)


__all__ = ["DanglingArtifactPointer", "find_dangling_artifact_pointers"]
