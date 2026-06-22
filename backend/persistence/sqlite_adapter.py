"""SQLite implementations of the persistence repository protocols."""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.plans.models import ApprovalRecord, PlanDocument, PlanStatus


_DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"


def _resolve_db_path(database_url: str) -> Path:
    url = (database_url or _DEFAULT_DATABASE_URL).strip()
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
    elif url.startswith("sqlite://"):
        raw = url.removeprefix("sqlite://")
    else:
        raise ValueError(
            f"SQLiteStore requires a sqlite:// DATABASE_URL. Got: {url!r}"
        )
    return Path(raw).expanduser().resolve()


class SQLiteStore:
    """SQLite-backed store implementing SessionRepository, RunRepository, and
    MessageRepository in a single connection-per-call style."""

    def __init__(self, database_url: str = _DEFAULT_DATABASE_URL) -> None:
        self.database_url = database_url
        self._database_path = _resolve_db_path(database_url)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._database_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    run_type TEXT NOT NULL DEFAULT 'existing_repo_change',
                    current_state TEXT NOT NULL DEFAULT 'starting',
                    trigger_message TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS run_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_key TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    sequence INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_runs_session_id ON runs(session_id);
                CREATE INDEX IF NOT EXISTS idx_run_steps_run_id ON run_steps(run_id, id);
                CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, sequence);
                """
            )
            self._ensure_column(conn, "runs", "run_type", "TEXT NOT NULL DEFAULT 'existing_repo_change'")
            self._ensure_column(conn, "runs", "current_state", "TEXT NOT NULL DEFAULT 'starting'")
            conn.commit()

    # ------------------------------------------------------------------
    # SessionRepository
    # ------------------------------------------------------------------

    def create_session(
        self,
        *,
        session_id: str,
        goal: str,
        plan: list[str],
        artifacts: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, goal, plan_json, artifacts_json) VALUES (?, ?, ?, ?)",
                (session_id, goal, json.dumps(plan), json.dumps(artifacts)),
            )
            conn.commit()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._decode_session(row)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [self._decode_session(row) for row in rows]  # type: ignore[misc]

    def update_session_artifacts(self, session_id: str, artifacts: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET artifacts_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(artifacts), session_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # RunRepository
    # ------------------------------------------------------------------

    def create_run(
        self,
        *,
        run_id: str,
        session_id: str,
        status: str,
        run_type: str,
        current_state: str,
        trigger_message: str,
        results: list[dict[str, Any]],
        steps: list[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, session_id, status, run_type, current_state, trigger_message, results_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, session_id, status, run_type, current_state, trigger_message, json.dumps(results)),
            )
            self._replace_run_steps(conn, run_id, steps)
            conn.commit()

    def update_run(
        self,
        *,
        run_id: str,
        status: str,
        current_state: str,
        results: list[dict[str, Any]],
        steps: list[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, current_state = ?, results_json = ?, completed_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (status, current_state, json.dumps(results), run_id),
            )
            self._replace_run_steps(conn, run_id, steps)
            conn.commit()

    def list_runs(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE session_id = ? ORDER BY rowid DESC", (session_id,)
            ).fetchall()
        return [self._decode_run(row) for row in rows]

    def list_run_steps(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT step_key, agent, status, started_at, completed_at, attempt "
                "FROM run_steps WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # MessageRepository
    # ------------------------------------------------------------------

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY sequence ASC", (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def append_messages(
        self,
        session_id: str,
        run_id: str,
        history: Iterable[dict[str, str]],
    ) -> None:
        existing = self.list_messages(session_id)
        start = len(existing)
        new_messages = list(history)[start:]
        if not new_messages:
            return
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO messages (session_id, run_id, sequence, role, content) VALUES (?, ?, ?, ?, ?)",
                [
                    (session_id, run_id, offset, item["role"], item["content"])
                    for offset, item in enumerate(new_messages, start=start)
                ],
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _decode_session(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "goal": row["goal"],
            "plan": json.loads(row["plan_json"]),
            "artifacts": json.loads(row["artifacts_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _decode_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "status": row["status"],
            "run_type": row["run_type"],
            "current_state": row["current_state"],
            "trigger_message": row["trigger_message"],
            "results": json.loads(row["results_json"]),
            "steps": self.list_run_steps(row["id"]),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _replace_run_steps(
        self, conn: sqlite3.Connection, run_id: str, steps: list[dict[str, Any]]
    ) -> None:
        conn.execute("DELETE FROM run_steps WHERE run_id = ?", (run_id,))
        if steps:
            conn.executemany(
                "INSERT INTO run_steps (run_id, step_key, agent, status, started_at, completed_at, attempt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        s["step_key"],
                        s["agent"],
                        s["status"],
                        s["started_at"],
                        s["completed_at"],
                        s.get("attempt", 1),
                    )
                    for s in steps
                ],
            )


class SQLitePlanStore:
    """SQLite implementation of PlanRepository."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        import os
        if db_path is not None:
            self._db_path = db_path
        else:
            url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
            self._db_path = _resolve_db_path(url)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _create_tables(self) -> None:
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

    def upsert_plan(self, session_id: str, steps: list[str]) -> None:
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
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, steps_json, status, updated_at FROM plan_documents WHERE session_id = ?",
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
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE plan_documents SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, now, session_id),
            )
            conn.commit()

    def approve(self, session_id: str, actor: str, note: str = "") -> None:
        self.set_status(session_id, PlanStatus.APPROVED)
        self._append_approval(session_id, decision=PlanStatus.APPROVED, actor=actor, note=note)

    def reject(self, session_id: str, actor: str, note: str = "") -> None:
        self.set_status(session_id, PlanStatus.REJECTED)
        self._append_approval(session_id, decision=PlanStatus.REJECTED, actor=actor, note=note)

    def list_plans(self) -> list[PlanDocument]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, steps_json, status, updated_at FROM plan_documents ORDER BY updated_at DESC"
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

    def _append_approval(
        self, session_id: str, decision: str, actor: str, note: str
    ) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO plan_approvals (session_id, decision, actor, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, decision, actor, note, now),
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()


__all__ = ["SQLitePlanStore", "SQLiteStore"]
