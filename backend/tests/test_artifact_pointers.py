"""Tests for the durable artifact pointer registry and reference-based GC (E8-S3).

Covers the story's remaining subtasks: the ``ArtifactPointerStore`` State
Store registry with tenant scoping (T2) and the reference-counted
``cleanup_unreferenced_artifacts`` sweep with its retention guard and
``--dry-run`` semantics (T4), following the fixture patterns of
``test_event_store.py`` and the local-store setup of
``test_artifact_store.py``.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.artifacts.cleanup import cleanup_unreferenced_artifacts
from backend.artifacts.pointers import ArtifactPointerStore, persist_artifact
from backend.artifacts.store import ArtifactKind, LocalArtifactStore
from backend.persistence.sqlite_adapter import SQLiteStore


@pytest.fixture()
def pointers(tmp_path: Path) -> ArtifactPointerStore:
    """Build an :class:`ArtifactPointerStore` on a throwaway SQLite database.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        A fresh pointer registry instance.
    """
    return ArtifactPointerStore(SQLiteStore(f"sqlite:///{tmp_path / 'state.db'}"))


@pytest.fixture()
def store(tmp_path: Path) -> LocalArtifactStore:
    """Build a local artifact store rooted in a temporary directory.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        A fresh local artifact store.
    """
    return LocalArtifactStore(root=tmp_path / "objects")


def _age(store: LocalArtifactStore, tmp_path: Path, relative: str, days: int) -> Path:
    """Backdate a stored local object's mtime by ``days`` days.

    Args:
        store: Local store the object was written to (unused; documents intent).
        tmp_path: Test temporary directory the store is rooted under.
        relative: Path of the object file relative to the store root.
        days: How many days into the past to move the mtime.

    Returns:
        The filesystem path of the aged object.
    """
    path = tmp_path / "objects" / relative
    old_mtime = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    os.utime(path, (old_mtime, old_mtime))
    return path


def test_pointer_round_trip_preserves_sha256_and_metadata(
    store: LocalArtifactStore, pointers: ArtifactPointerStore
) -> None:
    """A recorded pointer reads back with the exact digest and metadata."""
    payload = b"diff --git a/file.py b/file.py\n"
    pointer = store.put_artifact(
        ArtifactKind.PATCH,
        "tenant-a/run-1/change.diff",
        payload,
        content_type="text/x-diff",
    )

    recorded = pointers.record(
        pointer,
        kind=ArtifactKind.PATCH,
        tenant_id="tenant-a",
        context={"run_id": "run-1"},
    )
    fetched = pointers.get(recorded.id, tenant_id="tenant-a")

    assert fetched is not None
    assert fetched.sha256 == hashlib.sha256(payload).hexdigest()
    assert fetched.bucket == pointer.bucket
    assert fetched.object_key == "tenant-a/run-1/change.diff"
    assert fetched.size_bytes == len(payload)
    assert fetched.content_type == "text/x-diff"
    assert fetched.context == {"run_id": "run-1"}
    assert fetched.pointer == pointer
    by_key = pointers.find_by_key(
        pointer.bucket, pointer.object_key, tenant_id="tenant-a"
    )
    assert by_key is not None and by_key.id == recorded.id


def test_pointer_rerecord_same_key_upserts_in_place(
    store: LocalArtifactStore, pointers: ArtifactPointerStore
) -> None:
    """Re-recording the same (bucket, object_key) updates rather than duplicates."""
    pointer = store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/out.log", b"v1\n")
    pointers.record(pointer, kind=ArtifactKind.LOG, tenant_id="tenant-a")
    pointer2 = store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/out.log", b"v2!\n")
    pointers.record(pointer2, kind=ArtifactKind.LOG, tenant_id="tenant-a")

    records = pointers.list(tenant_id="tenant-a", kind=ArtifactKind.LOG)

    assert len(records) == 1
    assert records[0].sha256 == hashlib.sha256(b"v2!\n").hexdigest()


def test_pointer_reads_are_tenant_isolated(
    store: LocalArtifactStore, pointers: ArtifactPointerStore
) -> None:
    """Records owned by one tenant are invisible to reads scoped to another."""
    pointer = store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/out.log", b"log\n")
    recorded = pointers.record(pointer, kind=ArtifactKind.LOG, tenant_id="tenant-a")

    assert pointers.get(recorded.id, tenant_id="tenant-b") is None
    assert (
        pointers.find_by_key(pointer.bucket, pointer.object_key, tenant_id="tenant-b")
        is None
    )
    assert pointers.list(tenant_id="tenant-b") == []
    assert pointers.delete(recorded.id, tenant_id="tenant-b") is False
    assert pointers.get(recorded.id, tenant_id="tenant-a") is not None


def test_persist_artifact_stores_payload_and_registers_reference(
    store: LocalArtifactStore, pointers: ArtifactPointerStore
) -> None:
    """The helper writes the object and its key becomes a live reference."""
    recorded = persist_artifact(
        store,
        pointers,
        kind=ArtifactKind.RUN_EXPORT,
        object_key="tenant-a/run-1/report.json",
        payload=b"{}",
        content_type="application/json",
        tenant_id="tenant-a",
        context={"export": "weekly"},
    )

    assert store.get_artifact(recorded.bucket, recorded.object_key) == b"{}"
    assert "tenant-a/run-1/report.json" in pointers.referenced_object_keys()
    assert "tenant-a/run-1/report.json" in pointers.referenced_object_keys(
        bucket=recorded.bucket
    )


def test_gc_removes_old_orphans_and_preserves_referenced_objects(
    store: LocalArtifactStore, pointers: ArtifactPointerStore, tmp_path: Path
) -> None:
    """Only aged objects without a pointer row are swept, across tenants."""
    kept = persist_artifact(
        store,
        pointers,
        kind=ArtifactKind.LOG,
        object_key="tenant-a/run-1/kept.log",
        payload=b"keep\n",
        tenant_id="tenant-a",
    )
    store.put_artifact(ArtifactKind.LOG, "tenant-a/run-2/orphan.log", b"orphan\n")
    kept_path = _age(store, tmp_path, "logs/tenant-a/run-1/kept.log", days=30)
    orphan_path = _age(store, tmp_path, "logs/tenant-a/run-2/orphan.log", days=30)

    result = cleanup_unreferenced_artifacts(
        store, pointers, retention_days=7, dry_run=False
    )

    assert [item.object_key for item in result.removed] == ["tenant-a/run-2/orphan.log"]
    assert result.scanned_count == 2
    assert kept_path.exists()
    assert not orphan_path.exists()
    assert store.get_artifact(kept.bucket, kept.object_key) == b"keep\n"


def test_gc_age_guard_keeps_recent_orphans(
    store: LocalArtifactStore, pointers: ArtifactPointerStore, tmp_path: Path
) -> None:
    """Orphans younger than the retention window survive the sweep."""
    store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/fresh.log", b"fresh\n")

    result = cleanup_unreferenced_artifacts(
        store, pointers, retention_days=7, dry_run=False
    )

    assert result.removed == []
    assert (tmp_path / "objects" / "logs" / "tenant-a" / "run-1" / "fresh.log").exists()


def test_gc_dry_run_reports_without_deleting(
    store: LocalArtifactStore, pointers: ArtifactPointerStore, tmp_path: Path
) -> None:
    """A dry run lists doomed orphans while leaving every object on disk."""
    store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/orphan.log", b"orphan\n")
    orphan_path = _age(store, tmp_path, "logs/tenant-a/run-1/orphan.log", days=30)

    result = cleanup_unreferenced_artifacts(
        store, pointers, retention_days=7, dry_run=True
    )

    assert [item.object_key for item in result.removed] == ["tenant-a/run-1/orphan.log"]
    assert result.dry_run is True
    assert orphan_path.exists()


def test_gc_negative_retention_disables_collection(
    store: LocalArtifactStore, pointers: ArtifactPointerStore, tmp_path: Path
) -> None:
    """``retention_days=-1`` keeps even ancient orphans forever."""
    store.put_artifact(ArtifactKind.LOG, "tenant-a/run-1/ancient.log", b"ancient\n")
    ancient_path = _age(store, tmp_path, "logs/tenant-a/run-1/ancient.log", days=365)

    result = cleanup_unreferenced_artifacts(
        store, pointers, retention_days=-1, dry_run=False
    )

    assert result.removed == []
    assert result.scanned_count == 0
    assert ancient_path.exists()
