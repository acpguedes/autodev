"""Project identity, discovery and persistence (E62)."""

from backend.projects.discovery import discover_project_root, find_project_marker
from backend.projects.resolution import resolve_project, resolve_project_root
from backend.projects.store import ProjectRecord, ProjectStore
from backend.projects.models import (
    ProjectConfig,
    ProjectConfigError,
    ProjectGitInfo,
    ProjectMetadata,
    load_project_config,
    load_project_metadata,
)

__all__ = [
    "ProjectConfig",
    "ProjectConfigError",
    "ProjectGitInfo",
    "ProjectMetadata",
    "ProjectRecord",
    "ProjectStore",
    "discover_project_root",
    "find_project_marker",
    "load_project_config",
    "load_project_metadata",
    "resolve_project",
    "resolve_project_root",
]
