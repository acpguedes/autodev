"""SQLite-backed plan store with idempotent table creation.

This module adds two NEW tables (``plan_documents``, ``plan_approvals``) to
the *same* SQLite file used by the rest of the application.  It does NOT
touch ``DurableStore`` or ``database.py``.

The database path is resolved from the ``DATABASE_URL`` environment variable
(``sqlite:///...`` form) or from an explicit path passed to ``PlanStore``.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from backend.plans.models import ApprovalRecord, PlanDocument, PlanStatus


_DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"


def _resolve_db_path(database_url: str) -> Path:
    """Convert a ``sqlite:///...`` URL to a :class:`~pathlib.Path`."""
    url = database_url.strip() or _DEFAULT_DATABASE_URL
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
    elif url.startswith("sqlite://"):
        raw = url.removeprefix("sqlite://")
    else:
        raise ValueError(
            "PlanStore requires a sqlite DATABASE_URL (e.g. sqlite:///./autodev.db). "
            f"Got: {url!r}"
        )
    return Path(raw).expanduser().resolve()


class PlanStore:
    """Additive SQLite plan store.

    Tables created:
    - ``plan_documents``  — latest plan snapshot per session.
    - ``plan_approvals``  — append-only approval/rejection log per session.

    Parameters
    ----------
    db_path:
        Explicit filesystem path to the SQLite file.  When ``None`` the path
        is resolved from the ``DATABASE_URL`` environment variable (or the
        same default used by ``DurableStore``).
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is not None:
            self._db_path = db_path
        else:
            url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
            self._db_path = _resolve_db_path(url)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Create ``plan_documents`` and ``plan_approvals`` if absent."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS plan_documents (
                    session_id  TEXT PRIMARY KEY,
                    steps_json  TEXT NOT NULL DEFAULT '[]',
                    status      TEXT NOT NULL DEFAULT 'draft',
                    updated_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plan_approvals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    decision    TEXT NOT NULL,
                    actor       TEXT NOT NULL,
                    note        TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL
                );
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert_plan(self, session_id: str, steps: list[str]) -> None:
        """Insert or replace the plan for *session_id*.

        Resets status to ``draft`` on every upsert so a changed plan must be
        re-approved.
        """
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO plan_documents (session_id, steps_json, status, updated_at)
                VALUES (?, ?, 'draft', ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    steps_json = excluded.steps_json,
                    status     = 'draft',
                    updated_at = excluded.updated_at
                """,
                (session_id, json.dumps(steps), now),
            )
            conn.commit()

    def get_plan(self, session_id: str) -> Optional[PlanDocument]:
        """Return the latest plan for *session_id*, or ``None`` if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, steps_json, status, updated_at "
                "FROM plan_documents WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return PlanDocument(
            session_id=row["session_id"],
            steps=json.loads(row["steps_json"]),
            status=row["status"],
            updated_at=row["updated_at"],
        )

    def set_status(self, session_id: str, status: str) -> None:
        """Update the status field for an existing plan."""
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE plan_documents SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, now, session_id),
            )
            conn.commit()

    def approve(self, session_id: str, actor: str, note: str = "") -> None:
        """Approve the plan and append an approval record."""
        self.set_status(session_id, PlanStatus.APPROVED)
        self._append_approval(session_id, decision=PlanStatus.APPROVED, actor=actor, note=note)

    def reject(self, session_id: str, actor: str, note: str = "") -> None:
        """Reject the plan and append a rejection record."""
        self.set_status(session_id, PlanStatus.REJECTED)
        self._append_approval(session_id, decision=PlanStatus.REJECTED, actor=actor, note=note)

    def list_plans(self) -> list[PlanDocument]:
        """Return all plans, ordered by ``updated_at`` descending."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, steps_json, status, updated_at "
                "FROM plan_documents ORDER BY updated_at DESC"
            ).fetchall()
        return [
            PlanDocument(
                session_id=row["session_id"],
                steps=json.loads(row["steps_json"]),
                status=row["status"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def list_approvals(self, session_id: str) -> list[ApprovalRecord]:
        """Return all approval records for *session_id*."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, decision, actor, note, created_at "
                "FROM plan_approvals WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_approval(
        self, session_id: str, decision: str, actor: str, note: str
    ) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO plan_approvals (session_id, decision, actor, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, decision, actor, note, now),
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()


__all__ = ["PlanStore"]
