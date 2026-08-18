"""Durable store for environment lifecycle records and policy decisions (E32-S3/S4).

Mirrors :class:`backend.execution.policy.PolicyStore` /
:class:`backend.quotas.store.QuotaStore`: a plain SQLite-backed store
resolved from ``DATABASE_URL``, opened lazily per call.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"


def _now() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


def _now_plus(seconds: int) -> str:
    """Return an ISO-8601 timestamp *seconds* in the future."""
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _resolve_db_path(database_url: str) -> Path:
    """Resolve a ``sqlite://`` URL to a filesystem path, matching the core stores."""
    url = (database_url or _DEFAULT_DATABASE_URL).strip()
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
    elif url.startswith("sqlite://"):
        raw = url.removeprefix("sqlite://")
    else:
        raise ValueError(f"EnvironmentStore requires a sqlite:// DATABASE_URL. Got: {url!r}")
    return Path(raw).expanduser().resolve()


@dataclass(frozen=True, slots=True)
class EnvironmentRecord:
    """One durably persisted environment lifecycle record.

    Attributes:
        environment_id: Unique identifier for the provisioned instance.
        run_id: Orchestrator run this environment was provisioned for.
        tenant_id: Tenant the run belongs to.
        backend_kind: Resolved backend that provisioned this instance.
        profile_id: The environment profile's identifier.
        profile_hash: The environment profile's content hash (evidence, E32-S4-T2).
        workspace_path: Host path backing the workspace mount.
        status: ``"active"``, ``"collecting"``, ``"torn_down"``, or ``"orphaned"``.
        created_at: When this instance was provisioned.
        expires_at: TTL deadline; past this without teardown, the instance
            is reaped as an orphan.
        torn_down_at: When teardown completed, if it has.
    """

    environment_id: str
    run_id: str
    tenant_id: str
    backend_kind: str
    profile_id: str
    profile_hash: str
    workspace_path: str
    status: str
    created_at: str
    expires_at: str
    torn_down_at: Optional[str] = None


@dataclass(frozen=True, slots=True)
class EnvironmentDecisionRecord:
    """One durably persisted policy decision on a provisioned environment (E32-S4-T1).

    Attributes:
        decision_id: Unique identifier.
        environment_id: The environment this decision was evaluated against.
        run_id: Orchestrator run the environment belongs to.
        tenant_id: Tenant the run belongs to.
        category: ``"network"`` or ``"filesystem"``.
        target: The host or path the decision concerned.
        allowed: Whether the access was permitted.
        reason: Human-readable reason.
        decided_at: When the decision was recorded.
    """

    decision_id: str
    environment_id: str
    run_id: str
    tenant_id: str
    category: str
    target: str
    allowed: bool
    reason: str
    decided_at: str


class EnvironmentStore:
    """SQLite-backed durable store for environment records and policy decisions."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Open (creating if needed) the SQLite-backed environment tables.

        Args:
            db_path: Explicit database file path; defaults to resolving
                ``DATABASE_URL``.
        """
        self._db_path = db_path or _resolve_db_path(os.environ.get("DATABASE_URL", ""))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._create_schema(conn)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS execution_environments (
                environment_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                backend_kind TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                profile_hash TEXT NOT NULL,
                workspace_path TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                torn_down_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_execution_environments_run
                ON execution_environments(run_id);
            CREATE INDEX IF NOT EXISTS idx_execution_environments_tenant_status
                ON execution_environments(tenant_id, status, expires_at);
            CREATE TABLE IF NOT EXISTS execution_environment_decisions (
                decision_id TEXT PRIMARY KEY,
                environment_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                category TEXT NOT NULL,
                target TEXT NOT NULL,
                allowed INTEGER NOT NULL,
                reason TEXT NOT NULL,
                decided_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_execution_environment_decisions_env
                ON execution_environment_decisions(environment_id);
            """
        )

    def create_environment(self, record: EnvironmentRecord) -> None:
        """Durably persist a newly provisioned environment's record."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO execution_environments "
                "(environment_id, run_id, tenant_id, backend_kind, profile_id, profile_hash, "
                "workspace_path, status, created_at, expires_at, torn_down_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    record.environment_id,
                    record.run_id,
                    record.tenant_id,
                    record.backend_kind,
                    record.profile_id,
                    record.profile_hash,
                    record.workspace_path,
                    record.status,
                    record.created_at,
                    record.expires_at,
                ),
            )
            conn.commit()

    def count_active(self, tenant_id: str) -> int:
        """Return the tenant's current active (non-expired, non-torn-down) environment count."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM execution_environments "
                "WHERE tenant_id = ? AND status = 'active' AND expires_at > ?",
                (tenant_id, _now()),
            ).fetchone()
        return int(row["n"])

    def mark_status(
        self, environment_id: str, *, status: str, torn_down_at: Optional[str] = None
    ) -> bool:
        """Update an environment record's lifecycle status; return whether a row changed."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE execution_environments SET status = ?, torn_down_at = ? "
                "WHERE environment_id = ?",
                (status, torn_down_at, environment_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def get(self, environment_id: str) -> Optional[EnvironmentRecord]:
        """Fetch one environment record by id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_environments WHERE environment_id = ?",
                (environment_id,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list_for_run(self, run_id: str) -> list[EnvironmentRecord]:
        """List every environment record provisioned for one run (audit, E32-S4-T1)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_environments WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_expired_active(self, *, before: str) -> list[EnvironmentRecord]:
        """List active environments whose TTL has passed (orphan reaping, E32-S3-T1)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_environments WHERE status = 'active' AND expires_at <= ?",
                (before,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def record_decision(self, record: EnvironmentDecisionRecord) -> None:
        """Durably record one policy decision on a provisioned environment."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO execution_environment_decisions "
                "(decision_id, environment_id, run_id, tenant_id, category, target, allowed, "
                "reason, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.decision_id,
                    record.environment_id,
                    record.run_id,
                    record.tenant_id,
                    record.category,
                    record.target,
                    1 if record.allowed else 0,
                    record.reason,
                    record.decided_at,
                ),
            )
            conn.commit()

    def list_decisions_for_run(self, run_id: str) -> list[EnvironmentDecisionRecord]:
        """List every policy decision recorded for one run's environments (audit)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_environment_decisions WHERE run_id = ? "
                "ORDER BY decided_at",
                (run_id,),
            ).fetchall()
        return [
            EnvironmentDecisionRecord(
                decision_id=row["decision_id"],
                environment_id=row["environment_id"],
                run_id=row["run_id"],
                tenant_id=row["tenant_id"],
                category=row["category"],
                target=row["target"],
                allowed=bool(row["allowed"]),
                reason=row["reason"],
                decided_at=row["decided_at"],
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> EnvironmentRecord:
        return EnvironmentRecord(
            environment_id=row["environment_id"],
            run_id=row["run_id"],
            tenant_id=row["tenant_id"],
            backend_kind=row["backend_kind"],
            profile_id=row["profile_id"],
            profile_hash=row["profile_hash"],
            workspace_path=row["workspace_path"],
            status=row["status"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            torn_down_at=row["torn_down_at"],
        )


__all__ = ["EnvironmentDecisionRecord", "EnvironmentRecord", "EnvironmentStore"]
