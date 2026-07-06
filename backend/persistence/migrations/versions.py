"""Ordered migration lists for each SQLite store.

Each entry is a callable ``(conn: sqlite3.Connection) -> None`` that applies
exactly one incremental DDL step.  Add new migrations by appending to the
appropriate list — never edit or reorder existing entries.
"""

from __future__ import annotations

import sqlite3

from backend.persistence.migrations.runner import Migration, MigrationEntry

#: Core store tables retrofitted with a ``tenant_id`` column (E8-S1 scoped
#: slice — see ADR-010). Child/audit tables (``run_steps``, ``plugin_events``,
#: ``score_snapshot_promotions``) are scoped transitively through their
#: parent row's tenant and are intentionally not retrofitted directly.
TENANT_SCOPED_STORE_TABLES = (
    "sessions",
    "runs",
    "messages",
    "plugins",
    "eval_results",
    "score_snapshots",
)


# ---------------------------------------------------------------------------
# SQLiteStore migrations
# ---------------------------------------------------------------------------

def _m1_create_core_tables(conn: sqlite3.Connection) -> None:
    """Create the sessions, runs, run_steps, and messages tables and their indexes.

    Args:
        conn: SQLite connection to apply the migration on.
    """
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
    """Add the ``run_type`` column to ``runs`` if it does not already exist.

    Args:
        conn: SQLite connection to apply the migration on.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "run_type" not in existing:
        conn.execute(
            "ALTER TABLE runs ADD COLUMN run_type TEXT NOT NULL DEFAULT 'existing_repo_change'"
        )


def _m3_runs_add_current_state(conn: sqlite3.Connection) -> None:
    """Add the ``current_state`` column to ``runs`` if it does not already exist.

    Args:
        conn: SQLite connection to apply the migration on.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "current_state" not in existing:
        conn.execute(
            "ALTER TABLE runs ADD COLUMN current_state TEXT NOT NULL DEFAULT 'starting'"
        )


def _m4_create_plugin_tables(conn: sqlite3.Connection) -> None:
    """Create the plugins and plugin_events tables and their indexes.

    Args:
        conn: SQLite connection to apply the migration on.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS plugins (
            id TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            state TEXT NOT NULL,
            manifest_path TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS plugin_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            plugin_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_plugin_events_plugin_id ON plugin_events(plugin_id, id);
        """
    )


def _m5_create_eval_results_table(conn: sqlite3.Connection) -> None:
    """Create the eval_results table and its indexes (E5-S3).

    Results are keyed by ``(eval_id, eval_version, run_id)`` and never
    overwritten — each run inserts a new row, keeping history versioned and
    reproducible per the Evaluation Service's NFR.

    Args:
        conn: SQLite connection to apply the migration on.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS eval_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eval_id TEXT NOT NULL,
            eval_version TEXT NOT NULL,
            run_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            gate_passed INTEGER NOT NULL DEFAULT 1,
            document_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(eval_id, eval_version, run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_eval_results_eval_id
            ON eval_results(eval_id, eval_version, id DESC);
        """
    )


def _m6_create_score_snapshot_tables(conn: sqlite3.Connection) -> None:
    """Create the score_snapshots and score_snapshot_promotions tables (E5-S4).

    ``score_snapshots`` holds immutable, versioned Evaluation Service score
    snapshots (never overwritten — one row per ``snapshot_id``).
    ``score_snapshot_promotions`` is an append-only audit log of every
    promotion decision (promoted or blocked) a routing policy id's feedback
    loop makes; the latest ``promoted = 1`` row per ``policy_id`` is that
    policy's currently active snapshot.

    Args:
        conn: SQLite connection to apply the migration on.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS score_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL UNIQUE,
            sample_count INTEGER NOT NULL DEFAULT 0,
            document_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_score_snapshots_created
            ON score_snapshots(id DESC);

        CREATE TABLE IF NOT EXISTS score_snapshot_promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            baseline_snapshot_id TEXT NOT NULL DEFAULT '',
            promoted INTEGER NOT NULL,
            reason TEXT NOT NULL,
            decided_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_score_snapshot_promotions_policy_id
            ON score_snapshot_promotions(policy_id, id DESC);
        """
    )


def _m7_add_tenant_id_to_core_tables(conn: sqlite3.Connection) -> None:
    """Add a ``tenant_id`` column (default ``'default'``) to the core store tables.

    Scoped E8-S1 slice (ADR-010): backfills every existing row to the
    ``'default'`` tenant so current single-tenant callers keep working
    unchanged. SQLite has no Row-Level Security equivalent; tenant isolation
    on SQLite is enforced by callers appending
    :func:`backend.persistence.tenancy.sqlite_tenant_clause` to queries.

    Args:
        conn: SQLite connection to apply the migration on.
    """
    for table in TENANT_SCOPED_STORE_TABLES:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "tenant_id" not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")


def _m7_down_remove_tenant_id_from_core_tables(conn: sqlite3.Connection) -> None:
    """Revert :func:`_m7_add_tenant_id_to_core_tables` by dropping the ``tenant_id`` column.

    Args:
        conn: SQLite connection to apply the rollback on.
    """
    for table in TENANT_SCOPED_STORE_TABLES:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "tenant_id" in existing:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN tenant_id")


def _m8_create_code_chunks_table(conn: sqlite3.Connection) -> None:
    """Create the ``code_chunks`` table and its indexes (E7-S1-T4).

    Persists syntax-aware chunk metadata — file path, symbol, line span, and
    content hash — produced by :mod:`backend.repository.chunking`. Tenant-
    scoped from creation (E8-S1 slice, ADR-010): SQLite has no Row-Level
    Security equivalent, so isolation here is enforced by callers appending
    :func:`backend.persistence.tenancy.sqlite_tenant_clause` to queries.

    Args:
        conn: SQLite connection to apply the migration on.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS code_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            file_path TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT '',
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tenant_id, file_path, symbol, start_line)
        );

        CREATE INDEX IF NOT EXISTS idx_code_chunks_file_path
            ON code_chunks(tenant_id, file_path);

        CREATE INDEX IF NOT EXISTS idx_code_chunks_hash
            ON code_chunks(content_hash);
        """
    )


def _m8_down_drop_code_chunks_table(conn: sqlite3.Connection) -> None:
    """Revert :func:`_m8_create_code_chunks_table` by dropping the table.

    Args:
        conn: SQLite connection to apply the rollback on.
    """
    conn.execute("DROP TABLE IF EXISTS code_chunks")


def _m9_add_content_column_to_code_chunks(conn: sqlite3.Connection) -> None:
    """Add a ``content`` column to ``code_chunks`` (E7-S3-T1).

    Hybrid retrieval needs the chunk's actual source text to search/return —
    ``code_chunks`` previously stored only span/hash metadata. Defaults to
    ``''`` for any row indexed before this migration; a subsequent reindex
    repopulates it (:func:`backend.repository.indexing._upsert_chunk` now
    writes ``content`` on every insert/update).

    Args:
        conn: SQLite connection to apply the migration on.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)").fetchall()}
    if "content" not in existing:
        conn.execute("ALTER TABLE code_chunks ADD COLUMN content TEXT NOT NULL DEFAULT ''")


def _m9_down_remove_content_column_from_code_chunks(conn: sqlite3.Connection) -> None:
    """Revert :func:`_m9_add_content_column_to_code_chunks` by dropping the ``content`` column.

    Args:
        conn: SQLite connection to apply the rollback on.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)").fetchall()}
    if "content" in existing:
        conn.execute("ALTER TABLE code_chunks DROP COLUMN content")


STORE_MIGRATIONS: list[MigrationEntry] = [
    _m1_create_core_tables,
    _m2_runs_add_run_type,
    _m3_runs_add_current_state,
    _m4_create_plugin_tables,
    _m5_create_eval_results_table,
    _m6_create_score_snapshot_tables,
    Migration(
        up=_m7_add_tenant_id_to_core_tables,
        down=_m7_down_remove_tenant_id_from_core_tables,
        name="add_tenant_id_to_core_tables",
    ),
    Migration(
        up=_m8_create_code_chunks_table,
        down=_m8_down_drop_code_chunks_table,
        name="create_code_chunks_table",
    ),
    Migration(
        up=_m9_add_content_column_to_code_chunks,
        down=_m9_down_remove_content_column_from_code_chunks,
        name="add_content_column_to_code_chunks",
    ),
]


# ---------------------------------------------------------------------------
# SQLitePlanStore migrations
# ---------------------------------------------------------------------------

def _p1_create_plan_tables(conn: sqlite3.Connection) -> None:
    """Create the plan_documents and plan_approvals tables.

    Args:
        conn: SQLite connection to apply the migration on.
    """
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


#: Plan store tables retrofitted with a ``tenant_id`` column (E8-S1 scoped
#: slice — see ADR-010). Unlike ``run_steps``/``plugin_events``/
#: ``score_snapshot_promotions``, both ``plan_documents`` and
#: ``plan_approvals`` get their own column rather than being scoped
#: transitively — ``plan_approvals`` has no single parent row that is always
#: tenant-scoped at query time.
PLAN_STORE_TENANT_SCOPED_TABLES = ("plan_documents", "plan_approvals")


def _p2_add_tenant_id_to_plan_tables(conn: sqlite3.Connection) -> None:
    """Add a ``tenant_id`` column (default ``'default'``) to the plan store tables.

    Scoped E8-S1 slice (ADR-010): backfills every existing row to the
    ``'default'`` tenant so current single-tenant callers keep working
    unchanged. Mirrors :func:`_m7_add_tenant_id_to_core_tables` for the plan
    store's own tables.

    Args:
        conn: SQLite connection to apply the migration on.
    """
    for table in PLAN_STORE_TENANT_SCOPED_TABLES:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "tenant_id" not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")


def _p2_down_remove_tenant_id_from_plan_tables(conn: sqlite3.Connection) -> None:
    """Revert :func:`_p2_add_tenant_id_to_plan_tables` by dropping the ``tenant_id`` column.

    Args:
        conn: SQLite connection to apply the rollback on.
    """
    for table in PLAN_STORE_TENANT_SCOPED_TABLES:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "tenant_id" in existing:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN tenant_id")


PLAN_STORE_MIGRATIONS: list[MigrationEntry] = [
    _p1_create_plan_tables,
    Migration(
        up=_p2_add_tenant_id_to_plan_tables,
        down=_p2_down_remove_tenant_id_from_plan_tables,
        name="add_tenant_id_to_plan_tables",
    ),
]
