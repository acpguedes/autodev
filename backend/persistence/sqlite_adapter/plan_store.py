"""SQLite PlanRepository implementation."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from backend.persistence.codecs import dumps_json, loads_json, utcnow_iso
from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.versions import PLAN_STORE_MIGRATIONS
from backend.persistence.sqlite_adapter._shared import _DEFAULT_DATABASE_URL, _resolve_db_path
from backend.persistence.tenancy import DEFAULT_TENANT_ID, sqlite_tenant_clause
from backend.plans.models import ApprovalRecord, PlanDocument, PlanStatus


class SQLitePlanStore:
    """SQLite implementation of PlanRepository.

    Both ``plan_documents`` and ``plan_approvals`` carry their own
    ``tenant_id`` column (E8-S1 scoped slice — ADR-010); every method below
    filters/inserts using it via
    :func:`~backend.persistence.tenancy.sqlite_tenant_clause`.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is not None:
            self._db_path = db_path
        else:
            url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
            self._db_path = _resolve_db_path(url)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            MigrationRunner(conn, PLAN_STORE_MIGRATIONS, namespace="plan_store").run_pending()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_plan(
        self, session_id: str, steps: list[str], tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        """Create or replace a session's plan document, resetting its status to draft."""
        now = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO plan_documents (session_id, steps_json, status, updated_at, tenant_id)
                VALUES (?, ?, 'draft', ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    steps_json = excluded.steps_json,
                    status     = 'draft',
                    updated_at = excluded.updated_at,
                    tenant_id  = excluded.tenant_id
                """,
                (session_id, dumps_json(steps), now, tenant_id),
            )
            conn.commit()

    def get_plan(
        self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> Optional[PlanDocument]:
        """Fetch a session's plan document scoped to *tenant_id*, or ``None`` if not found."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT session_id, steps_json, status, updated_at FROM plan_documents "
                f"WHERE session_id = ? {clause}",
                (session_id, *params),
            ).fetchone()
        if row is None:
            return None
        return PlanDocument(
            session_id=row["session_id"],
            steps=loads_json(row["steps_json"]),
            status=row["status"],
            updated_at=row["updated_at"],
        )

    def set_status(
        self, session_id: str, status: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        """Update a session's plan status, scoped to *tenant_id*."""
        now = utcnow_iso()
        clause, params = sqlite_tenant_clause(tenant_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE plan_documents SET status = ?, updated_at = ? WHERE session_id = ? {clause}",
                (status, now, session_id, *params),
            )
            conn.commit()

    def approve(
        self, session_id: str, actor: str, note: str = "", tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        """Mark a session's plan as approved and record the approval."""
        self.set_status(session_id, PlanStatus.APPROVED, tenant_id=tenant_id)
        self._append_approval(
            session_id, decision=PlanStatus.APPROVED, actor=actor, note=note, tenant_id=tenant_id
        )

    def reject(
        self, session_id: str, actor: str, note: str = "", tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        """Mark a session's plan as rejected and record the rejection."""
        self.set_status(session_id, PlanStatus.REJECTED, tenant_id=tenant_id)
        self._append_approval(
            session_id, decision=PlanStatus.REJECTED, actor=actor, note=note, tenant_id=tenant_id
        )

    def list_plans(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[PlanDocument]:
        """List all plan documents scoped to *tenant_id*, most recently updated first."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT session_id, steps_json, status, updated_at FROM plan_documents "
                f"WHERE 1=1 {clause} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [
            PlanDocument(
                session_id=row["session_id"],
                steps=loads_json(row["steps_json"]),
                status=row["status"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def list_approvals(
        self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[ApprovalRecord]:
        """List all approval decisions for a session's plan scoped to *tenant_id*, oldest first."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT session_id, decision, actor, note, created_at "
                f"FROM plan_approvals WHERE session_id = ? {clause} ORDER BY created_at ASC",
                (session_id, *params),
            ).fetchall()
        return [
            ApprovalRecord(
                session_id=row["session_id"],
                decision=row["decision"],
                actor=row["actor"],
                note=row["note"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _append_approval(
        self,
        session_id: str,
        decision: str,
        actor: str,
        note: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        now = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO plan_approvals (session_id, decision, actor, note, created_at, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, decision, actor, note, now, tenant_id),
            )
            conn.commit()


__all__ = ["SQLitePlanStore"]
