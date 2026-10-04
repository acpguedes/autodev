"""v2 Control Plane API -- projects (E62-S4).

``GET /v2/projects`` lists the tenant's projects; the three no-project paths
are distinct operations: **open** an existing project, **initialize** an
existing directory (additive only -- see
:func:`backend.projects.service.initialize_project`) and **create** a new one.
Registering a filesystem root is an administrative act (``project:write``);
once registered, every other route resolves the root server-side from the
stored record and never from a client-supplied path.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.authorization import requires_scope
from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2, v2_error
from backend.projects.service import (
    ProjectConfigError,
    ProjectPathError,
    create_project,
    describe,
    initialize_project,
    open_project,
)
from backend.projects.store import ProjectRecord, ProjectStore

router = APIRouter(prefix="/v2/projects", tags=["projects"], dependencies=[Depends(require_v2_principal)])


class ProjectV2(BaseModel):
    """One project."""

    projectId: str
    name: str
    rootPath: str
    active: bool


class ProjectListV2(BaseModel):
    """Response body for ``GET /v2/projects``."""

    schemaVersion: str = SCHEMA_VERSION_V2
    items: list[ProjectV2]
    activeProjectId: str | None = None


class ProjectRootRequestV2(BaseModel):
    """Request body naming a project root, and optionally its name."""

    root: str = Field(..., min_length=1, description="Filesystem path of the project root.")
    name: str | None = Field(default=None, min_length=1, description="Project name; defaults to the directory name.")


def _view(record: ProjectRecord) -> ProjectV2:
    return ProjectV2(**describe(record))


@requires_scope("project:read")
@router.get("", response_model=ProjectListV2)
def list_projects_v2(principal: PrincipalV2 = Depends(require_v2_principal)) -> ProjectListV2:
    """List the caller's projects and which one is active."""
    items = [_view(r) for r in ProjectStore().list(tenant_id=principal.tenant_id)]
    active = next((p.projectId for p in items if p.active), None)
    return ProjectListV2(items=items, activeProjectId=active)


def _run(operation, principal: PrincipalV2, body: ProjectRootRequestV2, **kwargs) -> ProjectV2:
    try:
        return _view(operation(principal.tenant_id, body.root, **kwargs))
    except ProjectPathError as exc:
        v2_error(400, str(exc))
    except ProjectConfigError as exc:
        v2_error(422, str(exc))


@requires_scope("project:write")
@router.post("/open", response_model=ProjectV2)
def open_project_v2(
    body: ProjectRootRequestV2, principal: PrincipalV2 = Depends(require_v2_principal)
) -> ProjectV2:
    """Open an existing project (validate its ``.autodev/``) and activate it."""
    return _run(open_project, principal, body)


@requires_scope("project:write")
@router.post("/init", response_model=ProjectV2, status_code=201)
def initialize_project_v2(
    body: ProjectRootRequestV2, principal: PrincipalV2 = Depends(require_v2_principal)
) -> ProjectV2:
    """Configure an existing directory as a project without altering its contents."""
    return _run(initialize_project, principal, body, name=body.name)


@requires_scope("project:write")
@router.post("/create", response_model=ProjectV2, status_code=201)
def create_project_v2(
    body: ProjectRootRequestV2, principal: PrincipalV2 = Depends(require_v2_principal)
) -> ProjectV2:
    """Create a new project directory and initialize it."""
    return _run(create_project, principal, body, name=body.name)


@requires_scope("project:write")
@router.post("/{project_id}/activate", response_model=ProjectV2)
def activate_project_v2(
    project_id: str, principal: PrincipalV2 = Depends(require_v2_principal)
) -> ProjectV2:
    """Make a registered project the active one."""
    try:
        return _view(ProjectStore().activate(project_id, tenant_id=principal.tenant_id))
    except KeyError:
        v2_error(404, f"Unknown project_id {project_id!r}.")
