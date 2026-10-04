"""Typed on-disk project metadata (E62-S1-T2/T3).

A project is described by two files inside its ``.autodev/`` directory:
``config.json`` (per-project configuration overrides, legitimately ``{}``) and
``project.json`` (name and optional Git information). A project without Git is
still a project; an invalid file raises :class:`ProjectConfigError` naming the
file, and is never degraded into "no project found".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

#: Name of the marker directory that makes a directory a project root.
PROJECT_DIR_NAME = ".autodev"
#: Per-project configuration file inside the marker directory.
PROJECT_CONFIG_FILE = "config.json"
#: Project identity file inside the marker directory.
PROJECT_METADATA_FILE = "project.json"


class ProjectConfigError(ValueError):
    """Raised when a project's ``.autodev/`` file is unreadable or invalid.

    Attributes:
        path: The offending file.
    """

    def __init__(self, path: Path, problem: str) -> None:
        """Build the error.

        Args:
            path: File that failed to load.
            problem: Specific description of what is wrong with it.
        """
        self.path = path
        self.problem = problem
        super().__init__(f"{path}: {problem}")


class ProjectConfig(BaseModel):
    """Per-project configuration overrides; an empty object is valid."""

    model_config = ConfigDict(extra="allow")


class ProjectGitInfo(BaseModel):
    """Git information recorded when the project directory is a repository."""

    model_config = ConfigDict(extra="forbid")

    remote_url: str | None = None
    branch: str | None = None


class ProjectMetadata(BaseModel):
    """Contents of ``.autodev/project.json``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    git: ProjectGitInfo | None = None


def _read_json_object(path: Path) -> dict[str, Any]:
    """Read *path* as a JSON object, raising :class:`ProjectConfigError` otherwise."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectConfigError(path, f"cannot be read ({exc.strerror or exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectConfigError(path, f"is not valid JSON ({exc.msg} at line {exc.lineno})") from exc
    if not isinstance(data, dict):
        raise ProjectConfigError(path, "must contain a JSON object")
    return data


def _validate(model: type[BaseModel], path: Path, data: dict[str, Any]) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "<root>"
        raise ProjectConfigError(path, f"invalid field {where}: {first['msg']}") from exc


def load_project_config(project_root: Path) -> ProjectConfig:
    """Load ``<project_root>/.autodev/config.json``.

    Args:
        project_root: Project root directory.

    Returns:
        The parsed configuration; an empty :class:`ProjectConfig` when the file
        is absent.

    Raises:
        ProjectConfigError: If the file exists but is unreadable or invalid.
    """
    path = project_root / PROJECT_DIR_NAME / PROJECT_CONFIG_FILE
    if not path.exists():
        return ProjectConfig()
    return _validate(ProjectConfig, path, _read_json_object(path))


def load_project_metadata(project_root: Path) -> ProjectMetadata | None:
    """Load ``<project_root>/.autodev/project.json``.

    Args:
        project_root: Project root directory.

    Returns:
        The parsed metadata, or ``None`` when the file is absent.

    Raises:
        ProjectConfigError: If the file exists but is unreadable or invalid.
    """
    path = project_root / PROJECT_DIR_NAME / PROJECT_METADATA_FILE
    if not path.exists():
        return None
    return _validate(ProjectMetadata, path, _read_json_object(path))
