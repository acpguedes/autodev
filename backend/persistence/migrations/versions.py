"""Ordered migration lists for each SQLite store.

Each entry is a callable ``(conn: sqlite3.Connection) -> None`` that applies
exactly one incremental DDL step.  Add new migrations by appending to the
appropriate list — never edit or reorder existing entries.
"""

from __future__ import annotations

import sqlite3


# ---------------------------------------------------------------------------
# SQLiteStore migrations
# ---------------------------------------------------------------------------

def _m1_create_core_tables(conn: sqlite3.Connection) -> None:
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


def _m2_runs_add_run_type(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "run_type" not in existing:
        conn.execute(
            "ALTER TABLE runs ADD COLUMN run_type TEXT NOT NULL DEFAULT 'existing_repo_change'"
        )


def _m3_runs_add_current_state(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "current_state" not in existing:
        conn.execute(
            "ALTER TABLE runs ADD COLUMN current_state TEXT NOT NULL DEFAULT 'starting'"
        )


STORE_MIGRATIONS = [
    _m1_create_core_tables,
    _m2_runs_add_run_type,
    _m3_runs_add_current_state,
]


# ---------------------------------------------------------------------------
# SQLitePlanStore migrations
# ---------------------------------------------------------------------------

def _p1_create_plan_tables(conn: sqlite3.Connection) -> None:
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


PLAN_STORE_MIGRATIONS = [
    _p1_create_plan_tables,
]
