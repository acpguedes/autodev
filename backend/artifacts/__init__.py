"""Artifact storage backends for local and S3-compatible deployments."""

from .cleanup import (
    ArtifactObjectInfo,
    CleanupResult,
    cleanup_orphaned_artifacts,
    iter_all_objects,
)
from .store import (
    ArtifactKind,
    ArtifactPointer,
    ArtifactStore,
    LocalArtifactStore,
    MinioArtifactStore,
    all_bucket_names,
    get_artifact_store,
)

__all__ = [
    "ArtifactKind",
    "ArtifactObjectInfo",
    "ArtifactPointer",
    "ArtifactStore",
    "CleanupResult",
    "LocalArtifactStore",
    "MinioArtifactStore",
    "all_bucket_names",
    "cleanup_orphaned_artifacts",
    "get_artifact_store",
    "iter_all_objects",
]
