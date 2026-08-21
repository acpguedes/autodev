"""Postgres PlanRepository implementation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from backend.persistence.codecs import dumps_json, loads_json, utcnow_iso
from backend.persistence.migrations.postgres_versions import add_tenant_id_and_rls_to_plan_tables
from backend.persistence.postgres_adapter._shared import _DEFAULT_DATABASE_URL, _connect, _run_sql
from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant
from backend.plans.models import ApprovalRecord, PlanDocument, PlanStatus


class PostgresPlanStore:
    """Postgres-backed plan store."""

    def __init__(self, db_path: Optional[Path] = None, database_url: str = "") -> None:
        """Initialize the store and apply its migrations.

        Args:
            db_path: Unused; accepted for constructor-signature parity with
                the SQLite plan store.
            database_url: PostgreSQL connection URL; falls back to the
                ``DATABASE_URL`` env var.
        """
        del db_path
        self.database_url = database_url or os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
        with self.connect() as conn:
            self._run_migrations(conn)

    def connect(self) -> Any:
        """Open a new connection to this store's database."""
        return _connect(self.database_url)

    def _run_migrations(self, conn: Any) -> None:
        """Create the plan store's tables, apply tenancy DDL, and record the schema version.

        Calls :func:`add_tenant_id_and_rls_to_plan_tables` directly (rather
        than only relying on it running as a step in
        :data:`~backend.persistence.migrations.postgres_versions.POSTGRES_STORE_MIGRATIONS`)
        so this store is correctly tenant-scoped on its own, even if a
        :class:`~backend.persistence.postgres_adapter.store.PostgresStore` is
        never constructed against the same database (see that function's
        docstring for the full rationale).
        """
        _run_sql(
            conn,
            [
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    namespace TEXT PRIMARY KEY,
                    version INTEGER NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS plan_documents (
                    session_id TEXT PRIMARY KEY,
                    steps_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    status TEXT NOT NULL DEFAULT 'draft',
                    updated_at TEXT NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS plan_approvals (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """,
                """
                INSERT INTO schema_version (namespace, version)
                VALUES ('plan_store', 1)
                ON CONFLICT(namespace) DO UPDATE SET version = EXCLUDED.version
                """,
            ],
        )
        add_tenant_id_and_rls_to_plan_tables(conn)
        conn.commit()

    def upsert_plan(self, session_id: str, steps: list[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Create or replace a session's plan document, resetting its status to draft, scoped to *tenant_id*."""
        now = utcnow_iso()
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                """
                INSERT INTO plan_documents (session_id, steps_json, status, updated_at, tenant_id)
                VALUES (%s, %s::jsonb, 'draft', %s, %s)
                ON CONFLICT(session_id) DO UPDATE SET
                    steps_json = EXCLUDED.steps_json,
                    status = 'draft',
                    updated_at = EXCLUDED.updated_at
                """,
                (session_id, dumps_json(steps), now, tenant_id),
            )
            conn.commit()

    def get_plan(self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Optional[PlanDocument]:
        """Fetch a session's plan document, or ``None`` if it does not exist, scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                "SELECT session_id, steps_json, status, updated_at FROM plan_documents WHERE session_id = %s",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return PlanDocument(
            session_id=row[0],
            steps=loads_json(row[1]),
            status=row[2],
            updated_at=row[3],
        )

    def set_status(self, session_id: str, status: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Update a session's plan status, scoped to *tenant_id*."""
        now = utcnow_iso()
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                "UPDATE plan_documents SET status = %s, updated_at = %s WHERE session_id = %s",
                (status, now, session_id),
            )
            conn.commit()

    def approve(self, session_id: str, actor: str, note: str = "", tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Mark a session's plan as approved and record the approval, scoped to *tenant_id*."""
        self.set_status(session_id, PlanStatus.APPROVED, tenant_id=tenant_id)
        self._append_approval(
            session_id, decision=PlanStatus.APPROVED, actor=actor, note=note, tenant_id=tenant_id
        )

    def reject(self, session_id: str, actor: str, note: str = "", tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Mark a session's plan as rejected and record the rejection, scoped to *tenant_id*."""
        self.set_status(session_id, PlanStatus.REJECTED, tenant_id=tenant_id)
        self._append_approval(
            session_id, decision=PlanStatus.REJECTED, actor=actor, note=note, tenant_id=tenant_id
        )

    def list_plans(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[PlanDocument]:
        """List all plan documents visible to *tenant_id*, most recently updated first."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                "SELECT session_id, steps_json, status, updated_at FROM plan_documents ORDER BY updated_at DESC"
            ).fetchall()
        return [
            PlanDocument(
                session_id=row[0],
                steps=loads_json(row[1]),
                status=row[2],
                updated_at=row[3],
            )
            for row in rows
        ]

    def list_approvals(self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> list[ApprovalRecord]:
        """List all approval decisions for a session's plan, oldest first, scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                """
                SELECT session_id, decision, actor, note, created_at
                FROM plan_approvals WHERE session_id = %s ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            ApprovalRecord(
                session_id=row[0],
                decision=row[1],
                actor=row[2],
                note=row[3],
                created_at=row[4],
            )
            for row in rows
        ]

    def _append_approval(
        self, session_id: str, decision: str, actor: str, note: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        """Insert an approval decision record for a session, scoped to *tenant_id*."""
        now = utcnow_iso()
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                """
                INSERT INTO plan_approvals (session_id, decision, actor, note, created_at, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (session_id, decision, actor, note, now, tenant_id),
            )
            conn.commit()


__all__ = ["PostgresPlanStore"]
