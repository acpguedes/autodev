"""SQLite-backed durable state for the initial control-plane slice."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"


@dataclass(slots=True)
class DurableStore:
    """Repository wrapper for durable orchestration state."""

    database_url: str
    _database_path: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._database_path = self._resolve_database_path(self.database_url)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_tables()

    def create_tables(self) -> None:
        with self.connect() as connection:
            connection.executescript(
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
            self._ensure_column(connection, "runs", "run_type", "TEXT NOT NULL DEFAULT 'existing_repo_change'")
            self._ensure_column(connection, "runs", "current_state", "TEXT NOT NULL DEFAULT 'starting'")
            connection.commit()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def create_session(
        self,
        *,
        session_id: str,
        goal: str,
        plan: list[str],
        artifacts: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, goal, plan_json, artifacts_json)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, goal, json.dumps(plan), json.dumps(artifacts)),
            )
            connection.commit()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return self._decode_session(row)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [self._decode_session(row) for row in rows]

    def update_session_artifacts(self, session_id: str, artifacts: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET artifacts_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(artifacts), session_id),
            )
            connection.commit()

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
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (id, session_id, status, run_type, current_state, trigger_message, results_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, session_id, status, run_type, current_state, trigger_message, json.dumps(results)),
            )
            self._replace_run_steps(connection, run_id, steps)
            connection.commit()

    def update_run(
        self,
        *,
        run_id: str,
        status: str,
        current_state: str,
        results: list[dict[str, Any]],
        steps: list[dict[str, Any]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = ?, current_state = ?, results_json = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, current_state, json.dumps(results), run_id),
            )
            self._replace_run_steps(connection, run_id, steps)
            connection.commit()

    def list_runs(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE session_id = ? ORDER BY rowid DESC",
                (session_id,),
            ).fetchall()
        return [self._decode_run(row) for row in rows]

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY sequence ASC",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_messages(self, session_id: str, run_id: str, history: Iterable[dict[str, str]]) -> None:
        existing_messages = self.list_messages(session_id)
        start_sequence = len(existing_messages)
        new_messages = list(history)[start_sequence:]
        if not new_messages:
            return

        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO messages (session_id, run_id, sequence, role, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (session_id, run_id, offset, item["role"], item["content"])
                    for offset, item in enumerate(new_messages, start=start_sequence)
                ],
            )
            connection.commit()

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

    def list_run_steps(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT step_key, agent, status, started_at, completed_at, attempt
                FROM run_steps
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _resolve_database_path(self, database_url: str) -> Path:
        normalized = database_url.strip() or DEFAULT_DATABASE_URL
        if normalized.startswith("sqlite:///"):
            path = normalized.removeprefix("sqlite:///")
            return Path(path).expanduser().resolve()
        if normalized.startswith("sqlite://"):
            path = normalized.removeprefix("sqlite://")
            return Path(path).expanduser().resolve()
        raise ValueError(
            "The initial durable slice currently supports only sqlite DATABASE_URL values. "
            "Use a URL like sqlite:///./autodev.db."
        )

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        existing_columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing_columns:
            return
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")

    def _replace_run_steps(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        steps: list[dict[str, Any]],
    ) -> None:
        connection.execute("DELETE FROM run_steps WHERE run_id = ?", (run_id,))
        if not steps:
            return
        connection.executemany(
            """
            INSERT INTO run_steps (run_id, step_key, agent, status, started_at, completed_at, attempt)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    step["step_key"],
                    step["agent"],
                    step["status"],
                    step["started_at"],
                    step["completed_at"],
                    step.get("attempt", 1),
                )
                for step in steps
            ],
        )


@lru_cache(maxsize=1)
def get_store() -> DurableStore:
    """Return a cached durable store."""

    return DurableStore(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))


def reset_store_cache() -> None:
    """Clear the cached store, mainly for tests."""

    get_store.cache_clear()
