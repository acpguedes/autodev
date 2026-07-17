"""Artifact storage backends for local and S3-compatible deployments."""

from .cleanup import (
    ArtifactObjectInfo,
    CleanupResult,
    cleanup_orphaned_artifacts,
    cleanup_unreferenced_artifacts,
    iter_all_objects,
)
from .pointers import (
    ArtifactPointerStore,
    StoredArtifact,
    artifact_pointer_statements,
    persist_artifact,
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
    "ArtifactPointerStore",
    "ArtifactStore",
    "CleanupResult",
    "LocalArtifactStore",
    "MinioArtifactStore",
    "StoredArtifact",
    "all_bucket_names",
    "artifact_pointer_statements",
    "cleanup_orphaned_artifacts",
    "cleanup_unreferenced_artifacts",
    "get_artifact_store",
    "iter_all_objects",
    "persist_artifact",
]
