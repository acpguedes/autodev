"""Per-session project root resolution (E62-S3-T1).

The one place that turns "which project is this request about" into a
filesystem root, replacing the process-wide ``repository.project_root`` at
every consumer. The root is always read server-side from the stored project
record -- never accepted from a client.

Resolution order: the session's project, else an explicit project id, else
the tenant's active project, else the process-wide configured root (retained
as the fallback for installations and requests with no project at all).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.config.runtime import get_runtime_config_service
from backend.persistence import contract
from backend.persistence.database import get_store
from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant
from backend.projects.store import ProjectRecord, ProjectStore


def process_project_root() -> Path:
    """Return the process-wide configured project root (the legacy fallback)."""
    runtime_config = get_runtime_config_service().apply_to_environment()
    return Path(runtime_config.repository.project_root).resolve()


def session_project_id(session_id: str, *, tenant_id: str, store: Any = None) -> Optional[str]:
    """Return the project id *session_id* belongs to, or ``None``.

    Args:
        session_id: Session to look up.
        tenant_id: Owning tenant; a session of another tenant is not visible.
        store: State Store override; defaults to the configured one.

    Returns:
        The project id, or ``None`` for an unknown or unattached session.
    """
    state = store or get_store()
    is_pg = contract.is_postgres(getattr(state, "database_url", ""))
    with state.connect() as conn:
        if is_pg:
            set_postgres_tenant(conn, tenant_id)
        row = conn.execute(
            contract.sql("SELECT project_id FROM sessions WHERE id = {p} AND tenant_id = {p}", is_pg),
            (session_id, tenant_id),
        ).fetchone()
    return row[0] if row is not None and row[0] else None


def resolve_project(
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    store: Any = None,
) -> Optional[ProjectRecord]:
    """Resolve the project a request is about, or ``None`` when there is none.

    Args:
        tenant_id: Tenant scoping every lookup.
        session_id: Session carried by the request, if any.
        project_id: Explicit project id, used when there is no session project.
        store: State Store override.

    Returns:
        The project record per the module's resolution order (without the
        process-wide fallback, which has no record).
    """
    projects = ProjectStore(store=store)
    if session_id:
        pid = session_project_id(session_id, tenant_id=tenant_id, store=projects._store)
        if pid:
            found = projects.get(pid, tenant_id=tenant_id)
            if found is not None:
                return found
    if project_id:
        found = projects.get(project_id, tenant_id=tenant_id)
        if found is not None:
            return found
    return projects.get_active(tenant_id=tenant_id)


def resolve_project_root(
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    store: Any = None,
) -> Path:
    """Resolve the filesystem root for a request (see module docstring).

    Returns:
        The resolved project's root, else :func:`process_project_root`.
    """
    record = resolve_project(tenant_id=tenant_id, session_id=session_id, project_id=project_id, store=store)
    if record is not None:
        return Path(record.root_path).resolve()
    return process_project_root()


def session_id_from_request(request: Any) -> Optional[str]:
    """Return the session id a FastAPI request carries (path param, then query)."""
    value = request.path_params.get("session_id") or request.query_params.get("session_id")
    return str(value) if value else None
