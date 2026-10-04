"""Project identity, discovery and persistence (E62)."""

from backend.projects.discovery import discover_project_root, find_project_marker
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
    "discover_project_root",
    "find_project_marker",
    "load_project_config",
    "load_project_metadata",
]
