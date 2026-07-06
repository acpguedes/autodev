"""SQLite implementations of the persistence repository protocols."""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.plans.models import ApprovalRecord, PlanDocument, PlanStatus
from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.versions import PLAN_STORE_MIGRATIONS, STORE_MIGRATIONS
from backend.persistence.tenancy import DEFAULT_TENANT_ID, sqlite_tenant_clause


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
    MessageRepository in a single connection-per-call style.

    Every read/write is scoped to a ``tenant_id`` (default
    :data:`~backend.persistence.tenancy.DEFAULT_TENANT_ID`), per the E8-S1
    scoped multi-tenancy slice (ADR-010). SQLite has no Row-Level Security
    equivalent, so isolation is enforced here by appending
    :func:`~backend.persistence.tenancy.sqlite_tenant_clause` to hand-written
    queries on the tenant-scoped tables (``sessions``, ``runs``, ``messages``,
    ``eval_results``, ``score_snapshots``). ``run_steps`` and
    ``score_snapshot_promotions`` have no ``tenant_id`` column of their own by
    design — they are scoped transitively through their parent row's tenant
    via a ``JOIN``.
    """

    def __init__(self, database_url: str = _DEFAULT_DATABASE_URL) -> None:
        self.database_url = database_url
        self._database_path = _resolve_db_path(database_url)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            MigrationRunner(conn, STORE_MIGRATIONS, namespace="store").run_pending()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._database_path)
        conn.row_factory = sqlite3.Row
        return conn

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
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Insert a new session row scoped to *tenant_id*.

        Args:
            session_id: Unique identifier for the session.
            goal: The session's stated goal.
            plan: Ordered list of plan step descriptions.
            artifacts: Arbitrary session artifacts, serialized to JSON.
            tenant_id: Tenant the new session belongs to.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, goal, plan_json, artifacts_json, tenant_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, goal, json.dumps(plan), json.dumps(artifacts), tenant_id),
            )
            conn.commit()

    def get_session(
        self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, Any] | None:
        """Fetch a session by id scoped to *tenant_id*, or ``None`` if not found."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT * FROM sessions WHERE id = ? {clause}", (session_id, *params)
            ).fetchone()
        return self._decode_session(row)

    def list_sessions(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List all sessions for *tenant_id*, most recently created first."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM sessions WHERE 1=1 {clause} ORDER BY created_at DESC", params
            ).fetchall()
        return [self._decode_session(row) for row in rows]  # type: ignore[misc]

    def update_session_artifacts(
        self,
        session_id: str,
        artifacts: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Replace a session's stored artifacts, scoped to *tenant_id*."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE sessions SET artifacts_json = ?, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id = ? {clause}",
                (json.dumps(artifacts), session_id, *params),
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
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Insert a new run row (and its steps) scoped to *tenant_id*.

        Args:
            run_id: Unique identifier for the run.
            session_id: Identifier of the owning session.
            status: Current run status.
            run_type: Kind of run being executed.
            current_state: Current flow/state machine state.
            trigger_message: Message that triggered the run.
            results: Ordered list of result documents produced so far.
            steps: Ordered list of step records to persist alongside the run.
            tenant_id: Tenant the new run belongs to.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, session_id, status, run_type, current_state, "
                "trigger_message, results_json, tenant_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    session_id,
                    status,
                    run_type,
                    current_state,
                    trigger_message,
                    json.dumps(results),
                    tenant_id,
                ),
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
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Update a run's status, state, results, and steps, scoped to *tenant_id*."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE runs SET status = ?, current_state = ?, results_json = ?, "
                f"completed_at = CURRENT_TIMESTAMP WHERE id = ? {clause}",
                (status, current_state, json.dumps(results), run_id, *params),
            )
            self._replace_run_steps(conn, run_id, steps)
            conn.commit()

    def list_runs(
        self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List all runs for a session scoped to *tenant_id*, most recently created first."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM runs WHERE session_id = ? {clause} ORDER BY rowid DESC",
                (session_id, *params),
            ).fetchall()
        return [self._decode_run(row, tenant_id=tenant_id) for row in rows]

    def list_run_steps(
        self, run_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List all steps recorded for a run, in execution order.

        ``run_steps`` has no ``tenant_id`` column of its own (ADR-010); it is
        scoped transitively via a ``JOIN`` against its parent ``runs`` row.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT rs.step_key, rs.agent, rs.status, rs.started_at, rs.completed_at, rs.attempt "
                "FROM run_steps rs JOIN runs r ON rs.run_id = r.id "
                "WHERE rs.run_id = ? AND r.tenant_id = ? ORDER BY rs.id ASC",
                (run_id, tenant_id),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # MessageRepository
    # ------------------------------------------------------------------

    def list_messages(
        self, session_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List all messages for a session scoped to *tenant_id*, in sequence order."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM messages WHERE session_id = ? {clause} ORDER BY sequence ASC",
                (session_id, *params),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_messages(
        self,
        session_id: str,
        run_id: str,
        history: Iterable[dict[str, str]],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Append only the messages in ``history`` beyond what is already stored.

        Args:
            session_id: Identifier of the owning session.
            run_id: Identifier of the run that produced the messages.
            history: Full message history so far; only the tail beyond what is
                already persisted is inserted.
            tenant_id: Tenant the messages belong to.
        """
        existing = self.list_messages(session_id, tenant_id=tenant_id)
        start = len(existing)
        new_messages = list(history)[start:]
        if not new_messages:
            return
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO messages (session_id, run_id, sequence, role, content, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (session_id, run_id, offset, item["role"], item["content"], tenant_id)
                    for offset, item in enumerate(new_messages, start=start)
                ],
            )
            conn.commit()

    # ------------------------------------------------------------------
    # EvalResultRepository (E5-S3)
    # ------------------------------------------------------------------

    def create_eval_result(
        self,
        *,
        eval_id: str,
        eval_version: str,
        run_id: str,
        document: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Persist one eval result document scoped to *tenant_id* (E5-S3)."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO eval_results (eval_id, eval_version, run_id, mode, gate_passed, "
                "document_json, tenant_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    eval_id,
                    eval_version,
                    run_id,
                    str(document.get("mode", "offline")),
                    1 if (document.get("gate") or {}).get("passed", True) else 0,
                    json.dumps(document),
                    tenant_id,
                ),
            )
            conn.commit()

    def get_eval_result(
        self,
        eval_id: str,
        eval_version: str,
        run_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> dict[str, Any] | None:
        """Fetch one eval result document scoped to *tenant_id* (E5-S3)."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT document_json FROM eval_results WHERE eval_id = ? AND eval_version = ? "
                f"AND run_id = ? {clause}",
                (eval_id, eval_version, run_id, *params),
            ).fetchone()
        return json.loads(row["document_json"]) if row is not None else None

    def list_eval_results(
        self,
        eval_id: str,
        eval_version: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict[str, Any]]:
        """List eval result documents for an id scoped to *tenant_id*, newest first (E5-S3)."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            if eval_version is not None:
                rows = conn.execute(
                    f"SELECT document_json FROM eval_results WHERE eval_id = ? AND eval_version = ? "
                    f"{clause} ORDER BY id DESC",
                    (eval_id, eval_version, *params),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT document_json FROM eval_results WHERE eval_id = ? {clause} ORDER BY id DESC",
                    (eval_id, *params),
                ).fetchall()
        return [json.loads(row["document_json"]) for row in rows]

    # ------------------------------------------------------------------
    # ScoreSnapshotRepository (E5-S4)
    # ------------------------------------------------------------------

    def create_score_snapshot(
        self,
        *,
        snapshot_id: str,
        sample_count: int,
        document: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Persist one immutable, versioned score snapshot document scoped to *tenant_id* (E5-S4)."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO score_snapshots (snapshot_id, sample_count, document_json, tenant_id) "
                "VALUES (?, ?, ?, ?)",
                (snapshot_id, sample_count, json.dumps(document), tenant_id),
            )
            conn.commit()

    def get_score_snapshot(
        self, snapshot_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, Any] | None:
        """Fetch one persisted score snapshot document scoped to *tenant_id*, or ``None`` (E5-S4)."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT document_json FROM score_snapshots WHERE snapshot_id = ? {clause}",
                (snapshot_id, *params),
            ).fetchone()
        return json.loads(row["document_json"]) if row is not None else None

    def list_score_snapshots(
        self, limit: int = 50, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List persisted score snapshots scoped to *tenant_id*, newest first (E5-S4)."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT document_json FROM score_snapshots WHERE 1=1 {clause} "
                f"ORDER BY id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [json.loads(row["document_json"]) for row in rows]

    def record_snapshot_promotion(
        self,
        *,
        policy_id: str,
        snapshot_id: str,
        baseline_snapshot_id: str,
        promoted: bool,
        reason: str,
        decided_at: str,
        tenant_id: str = DEFAULT_TENANT_ID,  # noqa: ARG002 - see docstring
    ) -> None:
        """Append one promotion decision (promoted or blocked) to the audit log (E5-S4).

        ``score_snapshot_promotions`` has no ``tenant_id`` column of its own
        by design (ADR-010): it is scoped transitively through the referenced
        snapshot's tenant via ``snapshot_id`` (see
        :meth:`get_active_score_snapshot` and :meth:`list_snapshot_promotions`).
        *tenant_id* is accepted for interface parity with
        :class:`~backend.persistence.base.ScoreSnapshotRepository` but is not
        stored as a column on this audit-log table.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO score_snapshot_promotions "
                "(policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (policy_id, snapshot_id, baseline_snapshot_id, 1 if promoted else 0, reason, decided_at),
            )
            conn.commit()

    def get_active_score_snapshot(
        self, policy_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, Any] | None:
        """Fetch the currently promoted snapshot document for a policy id, scoped to *tenant_id* (E5-S4).

        Joins against ``score_snapshots`` on ``snapshot_id`` since
        ``score_snapshot_promotions`` has no ``tenant_id`` column of its own.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT ssp.snapshot_id FROM score_snapshot_promotions ssp "
                "JOIN score_snapshots ss ON ssp.snapshot_id = ss.snapshot_id "
                "WHERE ssp.policy_id = ? AND ssp.promoted = 1 AND ss.tenant_id = ? "
                "ORDER BY ssp.id DESC LIMIT 1",
                (policy_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        return self.get_score_snapshot(row["snapshot_id"], tenant_id=tenant_id)

    def list_snapshot_promotions(
        self, policy_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List every promotion decision recorded for a policy id, scoped to *tenant_id*, newest first (E5-S4).

        Joins against ``score_snapshots`` on ``snapshot_id`` since
        ``score_snapshot_promotions`` has no ``tenant_id`` column of its own.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT ssp.policy_id, ssp.snapshot_id, ssp.baseline_snapshot_id, ssp.promoted, "
                "ssp.reason, ssp.decided_at "
                "FROM score_snapshot_promotions ssp "
                "JOIN score_snapshots ss ON ssp.snapshot_id = ss.snapshot_id "
                "WHERE ssp.policy_id = ? AND ss.tenant_id = ? ORDER BY ssp.id DESC",
                (policy_id, tenant_id),
            ).fetchall()
        return [
            {
                "policyId": row["policy_id"],
                "snapshotId": row["snapshot_id"],
                "baselineSnapshotId": row["baseline_snapshot_id"],
                "promoted": bool(row["promoted"]),
                "reason": row["reason"],
                "decidedAt": row["decided_at"],
            }
            for row in rows
        ]

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

    def _decode_run(self, row: sqlite3.Row, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "status": row["status"],
            "run_type": row["run_type"],
            "current_state": row["current_state"],
            "trigger_message": row["trigger_message"],
            "results": json.loads(row["results_json"]),
            "steps": self.list_run_steps(row["id"], tenant_id=tenant_id),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

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
    """SQLite implementation of PlanRepository.

    Both ``plan_documents`` and ``plan_approvals`` carry their own
    ``tenant_id`` column (E8-S1 scoped slice — ADR-010); every method below
    filters/inserts using it via
    :func:`~backend.persistence.tenancy.sqlite_tenant_clause`.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        import os
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
        now = self._now()
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
                (session_id, json.dumps(steps), now, tenant_id),
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
            steps=json.loads(row["steps_json"]),
            status=row["status"],
            updated_at=row["updated_at"],
        )

    def set_status(
        self, session_id: str, status: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        """Update a session's plan status, scoped to *tenant_id*."""
        now = self._now()
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
                steps=json.loads(row["steps_json"]),
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
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO plan_approvals (session_id, decision, actor, note, created_at, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, decision, actor, note, now, tenant_id),
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()


__all__ = ["SQLitePlanStore", "SQLiteStore"]
