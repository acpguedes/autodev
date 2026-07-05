"""Artifact store contracts with local filesystem and MinIO backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
import hashlib
from io import BytesIO
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any

from backend.config.settings import Settings, get_settings


class ArtifactKind(StrEnum):
    """Category of artifact stored, mapping to a dedicated storage bucket."""

    PATCH = "patch"
    VALIDATION = "validation"
    RUN_EXPORT = "run-export"
    LOG = "log"


_KIND_BUCKETS: dict[ArtifactKind, str] = {
    ArtifactKind.PATCH: "patch-artifacts",
    ArtifactKind.VALIDATION: "validation-artifacts",
    ArtifactKind.RUN_EXPORT: "run-exports",
    ArtifactKind.LOG: "logs",
}


@dataclass(frozen=True)
class ArtifactPointer:
    """Metadata identifying a stored artifact.

    Attributes:
        bucket: Bucket the artifact was stored in.
        object_key: Relative object key within the bucket.
        sha256: SHA-256 digest of the stored payload.
        size_bytes: Size of the stored payload, in bytes.
        content_type: MIME type of the stored payload.
    """

    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    content_type: str


class ArtifactStore(ABC):
    """Abstract contract for artifact storage backends."""

    @abstractmethod
    def put_artifact(
        self,
        kind: ArtifactKind,
        object_key: str,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> ArtifactPointer:
        """Persist payload and return metadata needed by the State Store.

        Args:
            kind: Category of artifact, determining its target bucket.
            object_key: Relative POSIX path identifying the object within the bucket.
            payload: Raw bytes to store.
            content_type: MIME type to record for the stored object.

        Returns:
            A pointer describing where the artifact was stored.
        """

    @abstractmethod
    def get_artifact(self, bucket: str, object_key: str) -> bytes:
        """Return artifact bytes for a previously stored object.

        Args:
            bucket: Bucket the artifact was stored in.
            object_key: Relative object key within the bucket.

        Returns:
            The stored payload bytes.
        """


def _bucket_for(kind: ArtifactKind) -> str:
    """Resolve the storage bucket name for an artifact kind.

    Args:
        kind: Category of artifact.

    Returns:
        The bucket name associated with ``kind``.
    """
    return _KIND_BUCKETS[ArtifactKind(kind)]


def _validate_object_key(object_key: str) -> str:
    """Validate and normalize an object key, rejecting path traversal.

    Args:
        object_key: Candidate relative POSIX path.

    Returns:
        The trimmed, validated object key.

    Raises:
        ValueError: If the key is empty, absolute, or attempts path traversal.
    """
    key = object_key.strip()
    path = PurePosixPath(key)
    if (
        not key
        or key.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in key
    ):
        raise ValueError("object_key must be a relative POSIX path without traversal")
    return key


def _digest(payload: bytes) -> str:
    """Compute the SHA-256 digest of a payload.

    Args:
        payload: Bytes to hash.

    Returns:
        The hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(payload).hexdigest()


class LocalArtifactStore(ArtifactStore):
    """Filesystem-backed artifact store for local-first mode."""

    def __init__(self, root: str | Path) -> None:
        """Initialize the store rooted at a local directory, creating it if needed.

        Args:
            root: Directory to store artifact buckets under.
        """
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_artifact(
        self,
        kind: ArtifactKind,
        object_key: str,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> ArtifactPointer:
        """Persist payload to a local file under the artifact's bucket directory.

        Args:
            kind: Category of artifact, determining its target bucket.
            object_key: Relative POSIX path identifying the object within the bucket.
            payload: Raw bytes to store.
            content_type: MIME type to record for the stored object.

        Returns:
            A pointer describing where the artifact was stored.

        Raises:
            ValueError: If ``object_key`` is invalid or escapes the bucket directory.
        """
        bucket = _bucket_for(kind)
        key = _validate_object_key(object_key)
        target = (self.root / bucket / key).resolve()
        bucket_root = (self.root / bucket).resolve()
        if not target.is_relative_to(bucket_root):
            raise ValueError("object_key escapes artifact bucket")

        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            handle.write(payload)
            temp_path = Path(handle.name)
        temp_path.replace(target)
        return ArtifactPointer(
            bucket=bucket,
            object_key=key,
            sha256=_digest(payload),
            size_bytes=len(payload),
            content_type=content_type,
        )

    def get_artifact(self, bucket: str, object_key: str) -> bytes:
        """Read artifact bytes from the local filesystem.

        Args:
            bucket: Bucket the artifact was stored in.
            object_key: Relative object key within the bucket.

        Returns:
            The stored payload bytes.

        Raises:
            ValueError: If ``object_key`` is invalid or escapes the bucket directory.
        """
        key = _validate_object_key(object_key)
        target = (self.root / bucket / key).resolve()
        bucket_root = (self.root / bucket).resolve()
        if not target.is_relative_to(bucket_root):
            raise ValueError("object_key escapes artifact bucket")
        return target.read_bytes()


class MinioArtifactStore(ArtifactStore):
    """S3-compatible artifact store backed by MinIO."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        endpoint: str = "",
        access_key: str = "",
        secret_key: str = "",
        secure: bool = False,
    ) -> None:
        """Initialize the store, connecting to MinIO and ensuring buckets exist.

        Args:
            client: Pre-built MinIO client to reuse; a new one is built if omitted.
            endpoint: MinIO endpoint host, without scheme.
            access_key: MinIO access key.
            secret_key: MinIO secret key.
            secure: Whether to use HTTPS when connecting.

        Raises:
            RuntimeError: If the ``minio`` package is not installed.
            ValueError: If ``client`` is omitted and ``endpoint`` is blank.
        """
        if client is None:
            try:
                from minio import Minio  # type: ignore[import-untyped]
            except ImportError as exc:  # pragma: no cover - environment guard
                raise RuntimeError("minio package is not installed.") from exc
            if not endpoint.strip():
                raise ValueError("MinIO endpoint is required for s3 artifact storage")
            normalized_endpoint = endpoint.removeprefix("http://").removeprefix("https://")
            client = Minio(
                normalized_endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
            )
        self._client = client
        for bucket in _KIND_BUCKETS.values():
            self._ensure_bucket(bucket)

    def put_artifact(
        self,
        kind: ArtifactKind,
        object_key: str,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> ArtifactPointer:
        """Persist payload to MinIO under the artifact's bucket.

        Args:
            kind: Category of artifact, determining its target bucket.
            object_key: Relative POSIX path identifying the object within the bucket.
            payload: Raw bytes to store.
            content_type: MIME type to record for the stored object.

        Returns:
            A pointer describing where the artifact was stored.
        """
        bucket = _bucket_for(kind)
        key = _validate_object_key(object_key)
        self._ensure_bucket(bucket)
        self._client.put_object(
            bucket,
            key,
            BytesIO(payload),
            length=len(payload),
            content_type=content_type,
        )
        return ArtifactPointer(
            bucket=bucket,
            object_key=key,
            sha256=_digest(payload),
            size_bytes=len(payload),
            content_type=content_type,
        )

    def get_artifact(self, bucket: str, object_key: str) -> bytes:
        """Read artifact bytes from MinIO.

        Args:
            bucket: Bucket the artifact was stored in.
            object_key: Relative object key within the bucket.

        Returns:
            The stored payload bytes.
        """
        key = _validate_object_key(object_key)
        response = self._client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def _ensure_bucket(self, bucket: str) -> None:
        """Create a MinIO bucket if it does not already exist.

        Args:
            bucket: Name of the bucket to ensure.
        """
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)


def get_artifact_store(settings: Settings | None = None) -> ArtifactStore:
    """Build the configured artifact store backend.

    Args:
        settings: Settings override; falls back to :func:`get_settings`.

    Returns:
        A :class:`LocalArtifactStore` or :class:`MinioArtifactStore`, depending
        on ``settings.storage_backend``.
    """
    active = settings or get_settings()
    if active.storage_backend == "local":
        return LocalArtifactStore(active.autodev_artifact_dir)
    return MinioArtifactStore(
        endpoint=active.autodev_minio_endpoint,
        access_key=active.autodev_minio_access_key,
        secret_key=active.autodev_minio_secret_key,
        secure=active.autodev_minio_secure,
    )
