"""Durable store for projects (E62-S2-T2).

Runs on SQLite and PostgreSQL through the shared persistence contract (E49,
ADR-025): the connection always comes from the configured State Store, never
from a ``sqlite3`` import or ``DATABASE_URL`` lookup in this module. On
PostgreSQL ``projects`` carries forced tenant RLS, so every operation takes an
explicit ``tenant_id`` and scopes the transaction with it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from backend.persistence import contract
from backend.persistence.database import get_store
from backend.persistence.tenancy import set_postgres_tenant

_COLUMNS = "tenant_id, project_id, name, root_path, is_active, created_at"


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """One persisted project.

    Attributes:
        tenant_id: Owning tenant (the security boundary).
        project_id: Project identifier, unique within the tenant.
        name: Human-readable project name.
        root_path: Absolute, server-resolved filesystem root.
        is_active: Whether this is the tenant's active project.
        created_at: Creation timestamp, as stored.
    """

    tenant_id: str
    project_id: str
    name: str
    root_path: str
    is_active: bool
    created_at: str


class ProjectStore:
    """Persist and look up projects, scoped by tenant."""

    def __init__(self, *, store: Any = None) -> None:
        """Bind to an injected State Store or the process-wide configured one.

        Args:
            store: Store exposing ``connect()``; defaults to
                :func:`backend.persistence.database.get_store`.

        Raises:
            TypeError: If the resolved store does not expose ``connect()``.
        """
        self._store = store or get_store()
        if not hasattr(self._store, "connect"):
            raise TypeError("ProjectStore requires a durable store with connect()")

    @property
    def _is_postgres(self) -> bool:
        return contract.is_postgres(getattr(self._store, "database_url", ""))

    def _sql(self, template: str) -> str:
        return contract.sql(template, self._is_postgres)

    def _scope(self, conn: Any, tenant_id: str) -> None:
        if self._is_postgres:
            set_postgres_tenant(conn, tenant_id)

    @staticmethod
    def _record(row: Any) -> ProjectRecord:
        return ProjectRecord(
            tenant_id=row[0],
            project_id=row[1],
            name=row[2],
            root_path=row[3],
            is_active=bool(row[4]),
            created_at=str(row[5]),
        )

    def create(
        self,
        *,
        tenant_id: str,
        name: str,
        root_path: Path | str,
        project_id: Optional[str] = None,
        activate: bool = False,
    ) -> ProjectRecord:
        """Register a project, or return the existing one for the same root.

        Args:
            tenant_id: Owning tenant.
            name: Project name.
            root_path: Filesystem root; resolved to an absolute path.
            project_id: Explicit id; generated when omitted.
            activate: Make the new project the tenant's active one.

        Returns:
            The created record, or the already-registered record for
            ``root_path`` (idempotent registration).
        """
        root = str(Path(root_path).expanduser().resolve())
        existing = self.get_by_root(root, tenant_id=tenant_id)
        if existing is not None:
            return self.activate(existing.project_id, tenant_id=tenant_id) if activate else existing
        pid = project_id or f"proj_{uuid.uuid4().hex[:12]}"
        with self._store.connect() as conn:
            self._scope(conn, tenant_id)
            contract.begin_write(conn, self._is_postgres)
            conn.execute(
                self._sql(
                    "INSERT INTO projects (tenant_id, project_id, name, root_path, is_active) "
                    "VALUES ({p}, {p}, {p}, {p}, {p})"
                ),
                (tenant_id, pid, name, root, False),
            )
            conn.commit()
        created = self.get(pid, tenant_id=tenant_id)
        assert created is not None
        return self.activate(pid, tenant_id=tenant_id) if activate else created

    def get(self, project_id: str, *, tenant_id: str) -> Optional[ProjectRecord]:
        """Fetch one project by id within *tenant_id*."""
        return self._one("project_id = {p}", project_id, tenant_id)

    def get_by_root(self, root_path: Path | str, *, tenant_id: str) -> Optional[ProjectRecord]:
        """Fetch the project registered for *root_path* within *tenant_id*."""
        return self._one("root_path = {p}", str(Path(root_path).expanduser().resolve()), tenant_id)

    def get_active(self, *, tenant_id: str) -> Optional[ProjectRecord]:
        """Fetch the tenant's active project, or ``None`` if none is active."""
        with self._store.connect() as conn:
            self._scope(conn, tenant_id)
            row = conn.execute(
                self._sql(
                    f"SELECT {_COLUMNS} FROM projects WHERE tenant_id = {{p}} AND is_active = {{p}} "
                    "ORDER BY created_at LIMIT 1"
                ),
                (tenant_id, True),
            ).fetchone()
        return self._record(row) if row is not None else None

    def list(self, *, tenant_id: str) -> list[ProjectRecord]:
        """List the tenant's projects, oldest first."""
        with self._store.connect() as conn:
            self._scope(conn, tenant_id)
            rows = conn.execute(
                self._sql(
                    f"SELECT {_COLUMNS} FROM projects WHERE tenant_id = {{p}} ORDER BY created_at, project_id"
                ),
                (tenant_id,),
            ).fetchall()
        return [self._record(r) for r in rows]

    def activate(self, project_id: str, *, tenant_id: str) -> ProjectRecord:
        """Make *project_id* the tenant's only active project.

        Raises:
            KeyError: If the project does not exist for the tenant.
        """
        with self._store.connect() as conn:
            self._scope(conn, tenant_id)
            contract.begin_write(conn, self._is_postgres)
            found = conn.execute(
                self._sql("SELECT 1 FROM projects WHERE tenant_id = {p} AND project_id = {p}"),
                (tenant_id, project_id),
            ).fetchone()
            if found is None:
                conn.rollback()
                raise KeyError(project_id)
            conn.execute(
                self._sql("UPDATE projects SET is_active = {p} WHERE tenant_id = {p} AND is_active = {p}"),
                (False, tenant_id, True),
            )
            conn.execute(
                self._sql("UPDATE projects SET is_active = {p} WHERE tenant_id = {p} AND project_id = {p}"),
                (True, tenant_id, project_id),
            )
            conn.commit()
        record = self.get(project_id, tenant_id=tenant_id)
        assert record is not None
        return record

    def _one(self, clause: str, value: str, tenant_id: str) -> Optional[ProjectRecord]:
        with self._store.connect() as conn:
            self._scope(conn, tenant_id)
            row = conn.execute(
                self._sql(f"SELECT {_COLUMNS} FROM projects WHERE tenant_id = {{p}} AND {clause}"),
                (tenant_id, value),
            ).fetchone()
        return self._record(row) if row is not None else None
