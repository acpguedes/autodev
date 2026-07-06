"""Artifact store contracts with local filesystem and MinIO backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
import hashlib
from io import BytesIO
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any

from backend.config.settings import Settings, get_settings

#: Default validity window for pre-signed artifact URLs, in seconds.
DEFAULT_PRESIGNED_URL_EXPIRY_SECONDS = 3600


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

    def get_presigned_url(
        self,
        bucket: str,
        object_key: str,
        tenant_id: str,
        *,
        expires_in: int = DEFAULT_PRESIGNED_URL_EXPIRY_SECONDS,
    ) -> str:
        """Generate a time-limited URL granting temporary read access to an artifact.

        This is an optional capability: not every backend can produce a
        scoped, expiring link (a bare local filesystem has no HTTP endpoint
        to sign a URL for). Backends that support it override this method;
        the default implementation always raises.

        Args:
            bucket: Bucket the artifact was stored in.
            object_key: Relative object key within the bucket. Callers must
                pass a key already scoped to ``tenant_id`` (e.g. prefixed
                with ``f"{tenant_id}/"``), matching the convention used when
                the object was written via :meth:`put_artifact`.
            tenant_id: Tenant identifier the caller is scoped to; used to
                confirm the URL cannot resolve outside that tenant's prefix.
            expires_in: Number of seconds the URL remains valid.

        Returns:
            A pre-signed URL for temporary, read-only access to the object.

        Raises:
            NotImplementedError: If the backend does not support pre-signed
                URLs.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support pre-signed URLs"
        )


def _bucket_for(kind: ArtifactKind) -> str:
    """Resolve the storage bucket name for an artifact kind.

    Args:
        kind: Category of artifact.

    Returns:
        The bucket name associated with ``kind``.
    """
    return _KIND_BUCKETS[ArtifactKind(kind)]


def all_bucket_names() -> tuple[str, ...]:
    """List every bucket name an artifact store manages.

    Returns:
        The distinct bucket names backing all :class:`ArtifactKind` values,
        in declaration order. Used by lifecycle tooling (see
        :mod:`backend.artifacts.cleanup`) that must sweep every bucket
        without depending on ``ArtifactKind`` internals.
    """
    return tuple(_KIND_BUCKETS.values())


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


def _validate_tenant_scope(object_key: str, tenant_id: str) -> None:
    """Ensure a validated object key is scoped under the given tenant's prefix.

    Args:
        object_key: Already-validated, relative object key.
        tenant_id: Tenant identifier expected to prefix ``object_key``.

    Raises:
        ValueError: If ``tenant_id`` is blank or ``object_key`` does not
            start with ``f"{tenant_id}/"``.
    """
    tenant = tenant_id.strip()
    if not tenant:
        raise ValueError("tenant_id must not be blank")
    prefix = f"{tenant}/"
    if not object_key.startswith(prefix):
        raise ValueError(f"object_key must be scoped under tenant prefix '{prefix}'")


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

    def get_presigned_url(
        self,
        bucket: str,
        object_key: str,
        tenant_id: str,
        *,
        expires_in: int = DEFAULT_PRESIGNED_URL_EXPIRY_SECONDS,
    ) -> str:
        """Not supported: the local filesystem backend has no HTTP endpoint to sign a URL for."""
        raise NotImplementedError(
            "LocalArtifactStore has no HTTP endpoint fronting artifacts, "
            "so pre-signed URLs are not supported; use get_artifact() directly"
        )


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

    @property
    def client(self) -> Any:
        """Return the underlying MinIO client.

        Exposed read-only so closely related tooling (e.g. lifecycle
        cleanup in :mod:`backend.artifacts.cleanup`) can use native
        listing/removal APIs without this module growing every possible
        object-management operation.

        Returns:
            The MinIO (or MinIO-compatible test double) client instance.
        """
        return self._client

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

    def get_presigned_url(
        self,
        bucket: str,
        object_key: str,
        tenant_id: str,
        *,
        expires_in: int = DEFAULT_PRESIGNED_URL_EXPIRY_SECONDS,
    ) -> str:
        """Generate a pre-signed, time-limited URL for read access to an object.

        Delegates to the underlying MinIO client's native
        ``presigned_get_object``, which performs the AWS SigV4 signing; no
        signing is hand-rolled here. The resulting URL is valid only for the
        exact ``bucket``/``object_key`` pair given (scoped to a single
        object, never bucket-wide), so it cannot be used to reach any object
        outside ``object_key`` regardless of tenant.

        Args:
            bucket: Bucket the artifact was stored in.
            object_key: Relative object key within the bucket. Must be
                prefixed with ``f"{tenant_id}/"`` per the existing tenant
                scoping convention (see ``put_artifact`` callers), which is
                verified before signing.
            tenant_id: Tenant identifier the caller is scoped to.
            expires_in: Number of seconds the URL remains valid. Must be positive.

        Returns:
            A pre-signed URL granting temporary GET access to the object.

        Raises:
            ValueError: If ``object_key`` is invalid, is not scoped under
                ``tenant_id``, or ``expires_in`` is not positive.
        """
        key = _validate_object_key(object_key)
        _validate_tenant_scope(key, tenant_id)
        if expires_in <= 0:
            raise ValueError("expires_in must be a positive number of seconds")
        return self._client.presigned_get_object(
            bucket,
            key,
            expires=timedelta(seconds=expires_in),
        )

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
