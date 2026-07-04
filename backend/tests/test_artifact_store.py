"""Tests for E0-S6 artifact storage backends."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.artifacts.store import (
    ArtifactKind,
    LocalArtifactStore,
    MinioArtifactStore,
    get_artifact_store,
)
from backend.config.settings import Settings


def test_local_artifact_store_puts_and_gets_patch_artifact(tmp_path: Path) -> None:
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
    store = LocalArtifactStore(root=tmp_path)

    with pytest.raises(ValueError, match="object_key"):
        store.put_artifact(ArtifactKind.LOG, "../escape.log", b"nope")


class _FakeObject:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


class _FakeMinioClient:
    def __init__(self) -> None:
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], bytes] = {}

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
        self.buckets.add(bucket)

    def put_object(self, bucket: str, key: str, data, length: int, content_type: str) -> None:
        self.objects[(bucket, key)] = data.read(length)

    def get_object(self, bucket: str, key: str) -> _FakeObject:
        return _FakeObject(self.objects[(bucket, key)])


def test_minio_artifact_store_puts_and_gets_log_artifact() -> None:
    client = _FakeMinioClient()
    store = MinioArtifactStore(client=client)

    pointer = store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/stdout.log", b"ok\n")

    assert pointer.bucket == "logs"
    assert pointer.size_bytes == 3
    assert "logs" in client.buckets
    assert store.get_artifact(pointer.bucket, pointer.object_key) == b"ok\n"


def test_artifact_store_factory_preserves_local_first_without_external_dependencies(tmp_path: Path) -> None:
    settings = Settings(autodev_artifact_dir=str(tmp_path), storage_backend="local")

    store = get_artifact_store(settings)

    assert isinstance(store, LocalArtifactStore)
