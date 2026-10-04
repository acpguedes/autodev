"""The three no-project paths: open, initialize and create (E62-S4-T1/T4).

Configuring a directory is not restructuring it. :func:`initialize_project`
only ever *adds* ``.autodev/config.json`` and ``.autodev/project.json`` inside
a new or existing ``.autodev/`` directory: it never modifies, deletes or
reorders a pre-existing file, never touches ``.gitignore``, and never starts a
flow run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from backend.events.runtime import emit_event
from backend.projects.models import (
    PROJECT_CONFIG_FILE,
    PROJECT_DIR_NAME,
    PROJECT_METADATA_FILE,
    ProjectConfigError,
    ProjectGitInfo,
    ProjectMetadata,
    load_project_config,
    load_project_metadata,
)
from backend.projects.store import ProjectRecord, ProjectStore


class ProjectPathError(ValueError):
    """Raised when a requested project root cannot be used for the operation."""


def _read_git_info(root: Path) -> Optional[ProjectGitInfo]:
    """Read branch and ``origin`` URL from ``<root>/.git`` without running git.

    Returns ``None`` when *root* is not a plain Git work tree; absence is never
    an error.
    """
    git_dir = root / ".git"
    if not git_dir.is_dir():
        return None
    branch: Optional[str] = None
    remote: Optional[str] = None
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: refs/heads/"):
            branch = head[len("ref: refs/heads/"):]
        config = (git_dir / "config").read_text(encoding="utf-8")
        match = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', config)
        remote = match.group(1) if match else None
    except OSError:
        pass
    return ProjectGitInfo(remote_url=remote, branch=branch)


def _emit(type_: str, record: ProjectRecord) -> None:
    emit_event(
        type_,
        tenant_id=record.tenant_id,
        partition_key=record.tenant_id,
        data={"tenantId": record.tenant_id, "projectId": record.project_id, "name": record.name},
    )


def _register(store: ProjectStore, tenant_id: str, root: Path, name: str) -> ProjectRecord:
    """Register *root* (idempotent) and make it active, emitting catalog events."""
    known = store.get_by_root(root, tenant_id=tenant_id)
    record = store.create(tenant_id=tenant_id, name=name, root_path=root, activate=True)
    if known is None:
        _emit("project.created", record)
    _emit("project.activated", record)
    return record


def open_project(tenant_id: str, root: Path | str, *, store: Optional[ProjectStore] = None) -> ProjectRecord:
    """Open an existing project: validate its ``.autodev/`` and activate it.

    Args:
        tenant_id: Owning tenant.
        root: Project root containing ``.autodev/``.
        store: Store override.

    Returns:
        The activated project record.

    Raises:
        ProjectPathError: If *root* has no ``.autodev/`` directory.
        ProjectConfigError: If a metadata file inside it is invalid.
    """
    base = Path(root).expanduser().resolve()
    if not (base / PROJECT_DIR_NAME).is_dir():
        raise ProjectPathError(f"{base} is not an AutoDev project (no {PROJECT_DIR_NAME}/ directory)")
    load_project_config(base)
    metadata = load_project_metadata(base)
    return _register(store or ProjectStore(), tenant_id, base, metadata.name if metadata else base.name)


def initialize_project(
    tenant_id: str, root: Path | str, *, name: Optional[str] = None, store: Optional[ProjectStore] = None
) -> ProjectRecord:
    """Configure an existing directory as a project, preserving everything in it.

    Only missing ``.autodev/`` files are created; existing ones are kept as-is.
    No flow run is started.

    Args:
        tenant_id: Owning tenant.
        root: Existing directory.
        name: Project name; defaults to the metadata already on disk, else the
            directory name.
        store: Store override.

    Returns:
        The activated project record.

    Raises:
        ProjectPathError: If *root* is not an existing directory.
        ProjectConfigError: If an already-present metadata file is invalid.
    """
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise ProjectPathError(f"{base} is not an existing directory")
    marker = base / PROJECT_DIR_NAME
    marker.mkdir(exist_ok=True)
    config_path = marker / PROJECT_CONFIG_FILE
    meta_path = marker / PROJECT_METADATA_FILE
    if not config_path.exists():
        config_path.write_text("{}\n", encoding="utf-8")
    if not meta_path.exists():
        metadata = ProjectMetadata(name=(name or base.name), git=_read_git_info(base))
        meta_path.write_text(json.dumps(metadata.model_dump(), indent=2) + "\n", encoding="utf-8")
    return open_project(tenant_id, base, store=store)


def create_project(
    tenant_id: str, root: Path | str, *, name: Optional[str] = None, store: Optional[ProjectStore] = None
) -> ProjectRecord:
    """Create a new project directory, then initialize it.

    Args:
        tenant_id: Owning tenant.
        root: Directory to create; must not already exist (use
            :func:`initialize_project` for an existing one).
        name: Project name; defaults to the directory name.
        store: Store override.

    Returns:
        The activated project record.

    Raises:
        ProjectPathError: If *root* already exists.
    """
    base = Path(root).expanduser().resolve()
    if base.exists():
        raise ProjectPathError(f"{base} already exists; initialize it instead of creating it")
    base.mkdir(parents=True)
    return initialize_project(tenant_id, base, name=name, store=store)


def describe(record: ProjectRecord) -> dict[str, Any]:
    """Return a JSON-friendly view of *record*."""
    return {
        "projectId": record.project_id,
        "name": record.name,
        "rootPath": record.root_path,
        "active": record.is_active,
    }


__all__ = [
    "ProjectConfigError",
    "ProjectPathError",
    "create_project",
    "describe",
    "initialize_project",
    "open_project",
]
