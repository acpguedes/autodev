"""v2 Control Plane API -- read-only project file tree browser (E43-S4).

No existing endpoint lists the active session's ``project_root`` as a
browsable file tree or serves one file's raw content by relative path --
``/repository/context`` (``backend/api/main.py``) is ranked RAG search
context, not a tree. This router adds exactly that, read-only, guarded by
the same root-containment check :func:`backend.patches.engine.apply_patch`
already uses for writes, applied here to reads.

The platform currently has one project root per deployment (every other
``/v2`` router -- ``get_orchestrator_v2`` in ``sessions_v2.py``, the sandbox
policy -- resolves it the same way), not one per session, so there is no
per-session root to look up here either.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.api.authorization import requires_scope
from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2, v2_error
from backend.config.runtime import get_runtime_config_service

router = APIRouter(prefix="/v2/repository", dependencies=[Depends(require_v2_principal)])

# Noise directories never worth showing in a generated project's file browser.
_EXCLUDED_DIR_NAMES = frozenset({".git", "__pycache__", "node_modules", ".venv"})

# Refuse to inline anything larger than this in a file-read response; the
# viewer is for reading generated source, not downloading large artifacts.
_MAX_FILE_READ_BYTES = 1_000_000


def get_project_root_v2() -> Path:
    """Resolve the platform's single configured project root (E43-S4).

    Returns:
        The project root every browsed path must resolve inside of.
    """
    config_service = get_runtime_config_service()
    runtime_config = config_service.apply_to_environment()
    return Path(runtime_config.repository.project_root).resolve()


def _resolve_within_root(root: Path, relative_path: str) -> Path:
    """Resolve *relative_path* against *root*, rejecting any path traversal.

    Mirrors the containment guard in :func:`backend.patches.engine.apply_patch`
    (same ``resolve()`` + ``relative_to()`` check), applied to reads.

    Args:
        root: The guarded project root.
        relative_path: Caller-supplied path, relative to *root*. ``"."`` (or
            empty) resolves to *root* itself.

    Returns:
        The resolved, contained path.

    Raises:
        HTTPException: 400 if the path escapes *root*.
    """
    candidate = (root / (relative_path or ".")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        v2_error(400, f"Path traversal rejected: {relative_path!r} resolves outside the project root.")
    return candidate


class FileTreeEntryV2(BaseModel):
    """One immediate child of a browsed directory."""

    name: str
    path: str
    type: str
    size: int | None = None


class FileTreeV2(BaseModel):
    """Response body for ``GET /v2/repository/tree``."""

    schemaVersion: str = SCHEMA_VERSION_V2
    path: str
    entries: list[FileTreeEntryV2]


class FileContentV2(BaseModel):
    """Response body for ``GET /v2/repository/file``."""

    schemaVersion: str = SCHEMA_VERSION_V2
    path: str
    content: str
    size: int
    truncated: bool
    binary: bool


@requires_scope("repository:read")
@router.get("/tree", response_model=FileTreeV2, tags=["repository"])
def get_repository_tree_v2(
    path: str = Query(default="", description="Directory to list, relative to the project root."),
    project_root: Path = Depends(get_project_root_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> FileTreeV2:
    """List the immediate children of a directory inside the project root.

    Args:
        path: Directory to list, relative to the project root; ``""``/``"."``
            lists the root itself.
        project_root: The guarded project root.
        principal: Authenticated caller (read-only; no tenant scoping --
            the project root is a single, platform-wide workspace).

    Returns:
        The directory's immediate file/subdirectory children, sorted
        directories-first then by name.

    Raises:
        HTTPException: 400 if *path* escapes the project root; 404 if it
            does not exist or is not a directory.
    """
    target = _resolve_within_root(project_root, path)
    if not target.exists():
        v2_error(404, f"{path!r} does not exist.")
    if not target.is_dir():
        v2_error(404, f"{path!r} is not a directory.")

    entries: list[FileTreeEntryV2] = []
    for child in target.iterdir():
        if child.name in _EXCLUDED_DIR_NAMES:
            continue
        relative = child.relative_to(project_root).as_posix()
        if child.is_dir():
            entries.append(FileTreeEntryV2(name=child.name, path=relative, type="directory"))
        else:
            entries.append(
                FileTreeEntryV2(name=child.name, path=relative, type="file", size=child.stat().st_size)
            )
    entries.sort(key=lambda entry: (entry.type != "directory", entry.name.lower()))
    return FileTreeV2(path=target.relative_to(project_root).as_posix(), entries=entries)


@requires_scope("repository:read")
@router.get("/file", response_model=FileContentV2, tags=["repository"])
def get_repository_file_v2(
    path: str = Query(..., description="File to read, relative to the project root."),
    project_root: Path = Depends(get_project_root_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> FileContentV2:
    """Read one file's content by path, relative to the project root.

    Args:
        path: File to read, relative to the project root.
        project_root: The guarded project root.
        principal: Authenticated caller.

    Returns:
        The file's content (empty and ``binary: true`` if it is not valid
        UTF-8 text), tail-truncated at :data:`_MAX_FILE_READ_BYTES`.

    Raises:
        HTTPException: 400 if *path* escapes the project root; 404 if it
            does not exist or is not a regular file.
    """
    target = _resolve_within_root(project_root, path)
    if not target.exists():
        v2_error(404, f"{path!r} does not exist.")
    if not target.is_file():
        v2_error(404, f"{path!r} is not a file.")

    size = target.stat().st_size
    truncated = size > _MAX_FILE_READ_BYTES
    raw = target.read_bytes()[:_MAX_FILE_READ_BYTES]
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return FileContentV2(
            path=target.relative_to(project_root).as_posix(),
            content="",
            size=size,
            truncated=False,
            binary=True,
        )
    return FileContentV2(
        path=target.relative_to(project_root).as_posix(),
        content=content,
        size=size,
        truncated=truncated,
        binary=False,
    )


__all__ = ["get_project_root_v2", "get_repository_file_v2", "get_repository_tree_v2", "router"]
