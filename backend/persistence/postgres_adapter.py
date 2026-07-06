"""PostgreSQL implementations of the persistence repository protocols."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.postgres_versions import POSTGRES_STORE_MIGRATIONS
from backend.plans.models import ApprovalRecord, PlanDocument, PlanStatus

_DEFAULT_DATABASE_URL = "postgresql://autodev:autodev@postgres:5432/autodev"


def _connect(database_url: str) -> Any:
    """Open a new psycopg connection to the given PostgreSQL URL.

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        A new database connection.

    Raises:
        RuntimeError: If the ``psycopg`` package is not installed.
    """
    try:
        import psycopg  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError(
            "psycopg is required for PostgreSQL persistence. Install backend requirements."
        ) from exc
    return psycopg.connect(database_url)

def _json(value: Any) -> str:
    """Serialize a value to a JSON string."""
    return json.dumps(value)

def _loads(value: Any) -> Any:
    """Deserialize a JSON string, passing non-string values through unchanged."""
    if isinstance(value, str):
        return json.loads(value)
    return value

def _run_sql(conn: Any, statements: Iterable[str]) -> None:
    """Execute and commit a sequence of SQL statements on one connection."""
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()

class PostgresStore:
    """Postgres-backed store implementing sessions, runs, and messages."""

    def __init__(self, database_url: str = _DEFAULT_DATABASE_URL) -> None:
        """Initialize the store and apply its migrations.

        Args:
            database_url: PostgreSQL connection URL.
        """
        self.database_url = database_url
        with self.connect() as conn:
            self._run_migrations(conn)

    def connect(self) -> Any:
        """Open a new connection to this store's database."""
        return _connect(self.database_url)

    def _run_migrations(self, conn: Any) -> None:
        """Apply this store's versioned migrations via the shared runner.

        Uses the same :class:`MigrationRunner` machinery as
        :class:`~backend.persistence.sqlite_adapter.SQLiteStore`, running
        against a psycopg connection (``engine="postgres"``) instead of ad
        hoc ``CREATE TABLE IF NOT EXISTS`` statements. See
        ``backend/persistence/migrations/postgres_versions.py`` for the
        migration list.
        """
        MigrationRunner(
            conn, POSTGRES_STORE_MIGRATIONS, namespace="store", engine="postgres"
        ).run_pending()

    def create_session(
        self,
        *,
        session_id: str,
        goal: str,
        plan: list[str],
        artifacts: dict[str, Any],
    ) -> None:
        """Insert a new session row."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, goal, plan_json, artifacts_json) VALUES (%s, %s, %s::jsonb, %s::jsonb)",
                (session_id, goal, _json(plan), _json(artifacts)),
            )
            conn.commit()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Fetch a session by id, or ``None`` if it does not exist."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, goal, plan_json, artifacts_json, created_at, updated_at FROM sessions WHERE id = %s",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "goal": row[1],
            "plan": _loads(row[2]),
            "artifacts": _loads(row[3]),
            "created_at": str(row[4]),
            "updated_at": str(row[5]),
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions, most recently created first."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, goal, plan_json, artifacts_json, created_at, updated_at FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": row[0],
                "goal": row[1],
                "plan": _loads(row[2]),
                "artifacts": _loads(row[3]),
                "created_at": str(row[4]),
                "updated_at": str(row[5]),
            }
            for row in rows
        ]

    def update_session_artifacts(self, session_id: str, artifacts: dict[str, Any]) -> None:
        """Replace a session's stored artifacts."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET artifacts_json = %s::jsonb, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (_json(artifacts), session_id),
            )
            conn.commit()

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
        """Insert a new run row along with its steps."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (id, session_id, status, run_type, current_state, trigger_message, results_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (run_id, session_id, status, run_type, current_state, trigger_message, _json(results)),
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
        """Update a run's status, state, results, and steps."""
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = %s, current_state = %s, results_json = %s::jsonb, completed_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (status, current_state, _json(results), run_id),
            )
            self._replace_run_steps(conn, run_id, steps)
            conn.commit()

    def list_runs(self, session_id: str) -> list[dict[str, Any]]:
        """List all runs for a session, most recently created first."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, status, run_type, current_state, trigger_message,
                       results_json, created_at, completed_at
                FROM runs WHERE session_id = %s ORDER BY created_at DESC
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "session_id": row[1],
                "status": row[2],
                "run_type": row[3],
                "current_state": row[4],
                "trigger_message": row[5],
                "results": _loads(row[6]),
                "steps": self.list_run_steps(row[0]),
                "created_at": str(row[7]),
                "completed_at": str(row[8]),
            }
            for row in rows
        ]

    def list_run_steps(self, run_id: str) -> list[dict[str, Any]]:
        """List all steps recorded for a run, in execution order."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT step_key, agent, status, started_at, completed_at, attempt
                FROM run_steps WHERE run_id = %s ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "step_key": row[0],
                "agent": row[1],
                "status": row[2],
                "started_at": row[3],
                "completed_at": row[4],
                "attempt": row[5],
            }
            for row in rows
        ]

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        """List all messages for a session, in sequence order."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, run_id, sequence, role, content, created_at
                FROM messages WHERE session_id = %s ORDER BY sequence ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "session_id": row[1],
                "run_id": row[2],
                "sequence": row[3],
                "role": row[4],
                "content": row[5],
                "created_at": str(row[6]),
            }
            for row in rows
        ]

    def append_messages(
        self,
        session_id: str,
        run_id: str,
        history: Iterable[dict[str, str]],
    ) -> None:
        """Append only the messages in ``history`` beyond what is already stored."""
        existing = self.list_messages(session_id)
        start = len(existing)
        new_messages = list(history)[start:]
        if not new_messages:
            return
        with self.connect() as conn:
            with conn.cursor() as cur:
                for offset, item in enumerate(new_messages, start=start):
                    cur.execute(
                        """
                        INSERT INTO messages (session_id, run_id, sequence, role, content)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (session_id, run_id, offset, item["role"], item["content"]),
                    )
            conn.commit()

    def create_eval_result(
        self, *, eval_id: str, eval_version: str, run_id: str, document: dict[str, Any]
    ) -> None:
        """Persist one eval result document. Never overwrites an existing run (E5-S3)."""
        gate_passed = bool((document.get("gate") or {}).get("passed", True))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO eval_results (eval_id, eval_version, run_id, mode, gate_passed, document_json)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (eval_id, eval_version, run_id, str(document.get("mode", "offline")), gate_passed, _json(document)),
            )
            conn.commit()

    def get_eval_result(self, eval_id: str, eval_version: str, run_id: str) -> dict[str, Any] | None:
        """Fetch one eval result document, or ``None`` if it does not exist (E5-S3)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT document_json FROM eval_results WHERE eval_id = %s AND eval_version = %s AND run_id = %s",
                (eval_id, eval_version, run_id),
            ).fetchone()
        return _loads(row[0]) if row is not None else None

    def list_eval_results(self, eval_id: str, eval_version: str | None = None) -> list[dict[str, Any]]:
        """List eval result documents for an id, newest first, optionally by version (E5-S3)."""
        with self.connect() as conn:
            if eval_version is not None:
                rows = conn.execute(
                    "SELECT document_json FROM eval_results WHERE eval_id = %s AND eval_version = %s "
                    "ORDER BY id DESC",
                    (eval_id, eval_version),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT document_json FROM eval_results WHERE eval_id = %s ORDER BY id DESC",
                    (eval_id,),
                ).fetchall()
        return [_loads(row[0]) for row in rows]

    def create_score_snapshot(
        self, *, snapshot_id: str, sample_count: int, document: dict[str, Any]
    ) -> None:
        """Persist one immutable, versioned score snapshot document (E5-S4)."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO score_snapshots (snapshot_id, sample_count, document_json) "
                "VALUES (%s, %s, %s::jsonb)",
                (snapshot_id, sample_count, _json(document)),
            )
            conn.commit()

    def get_score_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Fetch one persisted score snapshot document, or ``None`` (E5-S4)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT document_json FROM score_snapshots WHERE snapshot_id = %s", (snapshot_id,)
            ).fetchone()
        return _loads(row[0]) if row is not None else None

    def list_score_snapshots(self, limit: int = 50) -> list[dict[str, Any]]:
        """List persisted score snapshots, newest first (E5-S4)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT document_json FROM score_snapshots ORDER BY id DESC LIMIT %s", (limit,)
            ).fetchall()
        return [_loads(row[0]) for row in rows]

    def record_snapshot_promotion(
        self,
        *,
        policy_id: str,
        snapshot_id: str,
        baseline_snapshot_id: str,
        promoted: bool,
        reason: str,
        decided_at: str,
    ) -> None:
        """Append one promotion decision (promoted or blocked) to the audit log (E5-S4)."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO score_snapshot_promotions "
                "(policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at),
            )
            conn.commit()

    def get_active_score_snapshot(self, policy_id: str) -> dict[str, Any] | None:
        """Fetch the currently promoted snapshot document for a policy id (E5-S4)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT snapshot_id FROM score_snapshot_promotions "
                "WHERE policy_id = %s AND promoted = TRUE ORDER BY id DESC LIMIT 1",
                (policy_id,),
            ).fetchone()
        if row is None:
            return None
        return self.get_score_snapshot(row[0])

    def list_snapshot_promotions(self, policy_id: str) -> list[dict[str, Any]]:
        """List every promotion decision recorded for a policy id, newest first (E5-S4)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at "
                "FROM score_snapshot_promotions WHERE policy_id = %s ORDER BY id DESC",
                (policy_id,),
            ).fetchall()
        return [
            {
                "policyId": row[0],
                "snapshotId": row[1],
                "baselineSnapshotId": row[2],
                "promoted": bool(row[3]),
                "reason": row[4],
                "decidedAt": row[5],
            }
            for row in rows
        ]

    def _replace_run_steps(self, conn: Any, run_id: str, steps: list[dict[str, Any]]) -> None:
        """Delete and re-insert all step rows for a run."""
        conn.execute("DELETE FROM run_steps WHERE run_id = %s", (run_id,))
        with conn.cursor() as cur:
            for step in steps:
                cur.execute(
                    """
                    INSERT INTO run_steps (run_id, step_key, agent, status, started_at, completed_at, attempt)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        step["step_key"],
                        step["agent"],
                        step["status"],
                        step["started_at"],
                        step["completed_at"],
                        step.get("attempt", 1),
                    ),
                )


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
        """Create the plan store's tables and record the schema version."""
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

    def upsert_plan(self, session_id: str, steps: list[str]) -> None:
        """Create or replace a session's plan document, resetting its status to draft."""
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO plan_documents (session_id, steps_json, status, updated_at)
                VALUES (%s, %s::jsonb, 'draft', %s)
                ON CONFLICT(session_id) DO UPDATE SET
                    steps_json = EXCLUDED.steps_json,
                    status = 'draft',
                    updated_at = EXCLUDED.updated_at
                """,
                (session_id, _json(steps), now),
            )
            conn.commit()

    def get_plan(self, session_id: str) -> Optional[PlanDocument]:
        """Fetch a session's plan document, or ``None`` if it does not exist."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT session_id, steps_json, status, updated_at FROM plan_documents WHERE session_id = %s",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return PlanDocument(
            session_id=row[0],
            steps=_loads(row[1]),
            status=row[2],
            updated_at=row[3],
        )

    def set_status(self, session_id: str, status: str) -> None:
        """Update a session's plan status."""
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE plan_documents SET status = %s, updated_at = %s WHERE session_id = %s",
                (status, now, session_id),
            )
            conn.commit()

    def approve(self, session_id: str, actor: str, note: str = "") -> None:
        """Mark a session's plan as approved and record the approval."""
        self.set_status(session_id, PlanStatus.APPROVED)
        self._append_approval(session_id, decision=PlanStatus.APPROVED, actor=actor, note=note)

    def reject(self, session_id: str, actor: str, note: str = "") -> None:
        """Mark a session's plan as rejected and record the rejection."""
        self.set_status(session_id, PlanStatus.REJECTED)
        self._append_approval(session_id, decision=PlanStatus.REJECTED, actor=actor, note=note)

    def list_plans(self) -> list[PlanDocument]:
        """List all plan documents, most recently updated first."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT session_id, steps_json, status, updated_at FROM plan_documents ORDER BY updated_at DESC"
            ).fetchall()
        return [
            PlanDocument(
                session_id=row[0],
                steps=_loads(row[1]),
                status=row[2],
                updated_at=row[3],
            )
            for row in rows
        ]

    def list_approvals(self, session_id: str) -> list[ApprovalRecord]:
        """List all approval decisions for a session's plan, oldest first."""
        with self.connect() as conn:
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

    def _append_approval(self, session_id: str, decision: str, actor: str, note: str) -> None:
        """Insert an approval decision record for a session."""
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO plan_approvals (session_id, decision, actor, note, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (session_id, decision, actor, note, now),
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        """Return the current UTC timestamp in ISO 8601 format."""
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

__all__ = ["PostgresPlanStore", "PostgresStore"]
