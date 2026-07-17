"""Tests for E0-S6 artifact storage backends and E8-S3 lifecycle additions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from pathlib import Path

import pytest

from backend.artifacts.cleanup import cleanup_orphaned_artifacts
from backend.artifacts.store import (
    ArtifactKind,
    LocalArtifactStore,
    MinioArtifactStore,
    get_artifact_store,
)
from backend.config.settings import Settings


def test_local_artifact_store_puts_and_gets_patch_artifact(tmp_path: Path) -> None:
    """The local store writes a patch artifact and reads back the same bytes."""
    store = LocalArtifactStore(root=tmp_path)
    payload = b"diff --git a/file.py b/file.py\n"

    pointer = store.put_artifact(
        ArtifactKind.PATCH,
        "tenant-a/run-1/change.diff",
        payload,
        content_type="text/x-diff",
    )

    assert pointer.bucket == "patch-artifacts"
    assert pointer.object_key == "tenant-a/run-1/change.diff"
    assert pointer.size_bytes == len(payload)
    assert pointer.sha256
    assert store.get_artifact(pointer.bucket, pointer.object_key) == payload


def test_local_artifact_store_rejects_path_traversal(tmp_path: Path) -> None:
    """The local store rejects object keys that attempt to escape their bucket."""
    store = LocalArtifactStore(root=tmp_path)

    with pytest.raises(ValueError, match="object_key"):
        store.put_artifact(ArtifactKind.LOG, "../escape.log", b"nope")


class _FakeObject:
    """In-memory stand-in for a MinIO response object."""

    def __init__(self, payload: bytes) -> None:
        """Wrap a fixed payload to be returned by :meth:`read`."""
        self._payload = payload

    def read(self) -> bytes:
        """Return the wrapped payload."""
        return self._payload

    def close(self) -> None:
        """No-op, present for interface parity with the real MinIO response."""
        pass

    def release_conn(self) -> None:
        """No-op, present for interface parity with the real MinIO response."""
        pass


class _FakeListedObject:
    """In-memory stand-in for a ``minio.datatypes.Object`` listing entry."""

    def __init__(self, object_name: str, size: int, last_modified: datetime) -> None:
        """Wrap the fields :func:`list_objects` callers rely on.

        Args:
            object_name: Relative object key within the bucket.
            size: Size of the object, in bytes.
            last_modified: Timestamp the object was last written.
        """
        self.object_name = object_name
        self.size = size
        self.last_modified = last_modified
        self.is_dir = False


class _FakeMinioClient:
    """In-memory stand-in for a MinIO client, used to test :class:`MinioArtifactStore`."""

    def __init__(self) -> None:
        """Initialize empty in-memory buckets and objects."""
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], bytes] = {}
        self.last_modified: dict[tuple[str, str], datetime] = {}
        self.presigned_urls: list[tuple[str, str, timedelta]] = []

    def bucket_exists(self, bucket: str) -> bool:
        """Return whether a bucket has been created."""
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
        """Record a bucket as created."""
        self.buckets.add(bucket)

    def put_object(self, bucket: str, key: str, data: BytesIO, length: int, content_type: str) -> None:
        """Store an object's bytes, read from a file-like ``data`` stream."""
        self.objects[(bucket, key)] = data.read(length)
        self.last_modified.setdefault((bucket, key), datetime.now(timezone.utc))

    def get_object(self, bucket: str, key: str) -> _FakeObject:
        """Return a fake response object wrapping the stored bytes."""
        return _FakeObject(self.objects[(bucket, key)])

    def presigned_get_object(self, bucket_name: str, object_name: str, expires: timedelta) -> str:
        """Record the call and return a deterministic fake pre-signed URL."""
        self.presigned_urls.append((bucket_name, object_name, expires))
        return f"https://minio.example.test/{bucket_name}/{object_name}?expires={int(expires.total_seconds())}"

    def list_objects(self, bucket_name: str, recursive: bool = False) -> list[_FakeListedObject]:
        """List fake objects stored under ``bucket_name``."""
        return [
            _FakeListedObject(
                object_name=key,
                size=len(payload),
                last_modified=self.last_modified.get((bucket, key), datetime.now(timezone.utc)),
            )
            for (bucket, key), payload in self.objects.items()
            if bucket == bucket_name
        ]

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        """Delete a fake object, mirroring the real client's ``remove_object``."""
        self.objects.pop((bucket_name, object_name), None)
        self.last_modified.pop((bucket_name, object_name), None)


def test_minio_artifact_store_puts_and_gets_log_artifact() -> None:
    """The MinIO-backed store writes a log artifact and reads back the same bytes."""
    client = _FakeMinioClient()
    store = MinioArtifactStore(client=client)

    pointer = store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/stdout.log", b"ok\n")

    assert pointer.bucket == "logs"
    assert pointer.size_bytes == 3
    assert "logs" in client.buckets
    assert store.get_artifact(pointer.bucket, pointer.object_key) == b"ok\n"


def test_artifact_store_factory_preserves_local_first_without_external_dependencies(tmp_path: Path) -> None:
    """The factory returns a local store when ``storage_backend`` is ``"local"``."""
    settings = Settings(autodev_artifact_dir=str(tmp_path), storage_backend="local")

    store = get_artifact_store(settings)

    assert isinstance(store, LocalArtifactStore)


# --- E8-S3/T3: pre-signed URLs ---


def test_minio_artifact_store_generates_presigned_url_scoped_to_tenant() -> None:
    """A pre-signed URL is generated via the native MinIO client, scoped to one object."""
    client = _FakeMinioClient()
    store = MinioArtifactStore(client=client)
    pointer = store.put_artifact(ArtifactKind.PATCH, "tenant-a/run-1/change.diff", b"diff\n")

    url = store.get_presigned_url(pointer.bucket, pointer.object_key, "tenant-a", expires_in=120)

    assert url == f"https://minio.example.test/{pointer.bucket}/{pointer.object_key}?expires=120"
    assert client.presigned_urls == [(pointer.bucket, pointer.object_key, timedelta(seconds=120))]


def test_minio_artifact_store_presigned_url_rejects_key_outside_tenant_scope() -> None:
    """A pre-signed URL request is rejected when the key isn't scoped to the given tenant."""
    client = _FakeMinioClient()
    store = MinioArtifactStore(client=client)
    pointer = store.put_artifact(ArtifactKind.PATCH, "tenant-a/run-1/change.diff", b"diff\n")

    with pytest.raises(ValueError, match="tenant prefix"):
        store.get_presigned_url(pointer.bucket, pointer.object_key, "tenant-b")


def test_minio_artifact_store_presigned_url_rejects_non_positive_expiry() -> None:
    """A pre-signed URL request is rejected when ``expires_in`` is not positive."""
    client = _FakeMinioClient()
    store = MinioArtifactStore(client=client)
    pointer = store.put_artifact(ArtifactKind.PATCH, "tenant-a/run-1/change.diff", b"diff\n")

    with pytest.raises(ValueError, match="expires_in"):
        store.get_presigned_url(pointer.bucket, pointer.object_key, "tenant-a", expires_in=0)


def test_local_artifact_store_get_presigned_url_not_implemented(tmp_path: Path) -> None:
    """The local backend has no HTTP endpoint to sign, so it raises clearly instead of faking one."""
    store = LocalArtifactStore(root=tmp_path)
    pointer = store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/stdout.log", b"ok\n")

    with pytest.raises(NotImplementedError, match="pre-signed URLs"):
        store.get_presigned_url(pointer.bucket, pointer.object_key, "tenant-a")


# --- E8-S3/T4: orphaned artifact cleanup ---


def test_cleanup_orphaned_artifacts_removes_old_unreferenced_local_objects(tmp_path: Path) -> None:
    """Objects older than the retention window and not referenced are removed."""
    store = LocalArtifactStore(root=tmp_path)
    store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/old.log", b"old\n")
    old_path = tmp_path / "logs" / "tenant-a" / "run-1" / "old.log"
    old_mtime = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(old_path, (old_mtime, old_mtime))

    result = cleanup_orphaned_artifacts(store, older_than=timedelta(days=7))

    assert result.scanned_count == 1
    assert result.dry_run is False
    assert [item.object_key for item in result.removed] == ["tenant-a/run-1/old.log"]
    assert not old_path.exists()


def test_cleanup_orphaned_artifacts_keeps_referenced_and_recent_local_objects(tmp_path: Path) -> None:
    """Referenced objects and recent objects both survive a cleanup sweep."""
    store = LocalArtifactStore(root=tmp_path)
    store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/referenced.log", b"keep\n")
    store.put_artifact(ArtifactKind.LOG, "tenant-a/run-2/recent.log", b"recent\n")
    referenced_path = tmp_path / "logs" / "tenant-a" / "run-1" / "referenced.log"
    old_mtime = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(referenced_path, (old_mtime, old_mtime))

    result = cleanup_orphaned_artifacts(
        store,
        older_than=timedelta(days=7),
        referenced_object_keys={"tenant-a/run-1/referenced.log"},
    )

    assert result.removed == []
    assert result.scanned_count == 2
    assert referenced_path.exists()
    assert (tmp_path / "logs" / "tenant-a" / "run-2" / "recent.log").exists()


def test_cleanup_orphaned_artifacts_dry_run_does_not_delete(tmp_path: Path) -> None:
    """A dry run reports orphaned objects without deleting anything."""
    store = LocalArtifactStore(root=tmp_path)
    store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/old.log", b"old\n")
    old_path = tmp_path / "logs" / "tenant-a" / "run-1" / "old.log"
    old_mtime = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(old_path, (old_mtime, old_mtime))

    result = cleanup_orphaned_artifacts(store, older_than=timedelta(days=7), dry_run=True)

    assert [item.object_key for item in result.removed] == ["tenant-a/run-1/old.log"]
    assert result.dry_run is True
    assert old_path.exists()


def test_cleanup_orphaned_artifacts_minio_backend_removes_old_unreferenced_objects() -> None:
    """The cleanup sweep works against the MinIO backend via the native client."""
    client = _FakeMinioClient()
    store = MinioArtifactStore(client=client)
    old_pointer = store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/old.log", b"old\n")
    fresh_pointer = store.put_artifact(ArtifactKind.LOG, "tenant-a/run-2/fresh.log", b"fresh\n")
    client.last_modified[(old_pointer.bucket, old_pointer.object_key)] = datetime.now(
        timezone.utc
    ) - timedelta(days=30)

    result = cleanup_orphaned_artifacts(store, older_than=timedelta(days=7))

    assert [item.object_key for item in result.removed] == [old_pointer.object_key]
    assert (old_pointer.bucket, old_pointer.object_key) not in client.objects
    assert (fresh_pointer.bucket, fresh_pointer.object_key) in client.objects
