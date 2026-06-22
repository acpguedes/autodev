"""PostgreSQL store — scaffold only.

TODO: Implement PostgresStore and PostgresPlanStore using asyncpg or psycopg3.
      All methods below raise NotImplementedError until then.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from backend.plans.models import ApprovalRecord, PlanDocument


class PostgresStore:
    """Postgres-backed store (not yet implemented).

    Satisfies the same interface as SQLiteStore so the factory can return it
    without callers needing to know the backend.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        raise NotImplementedError(
            "PostgresStore is not yet implemented. "
            "Use a sqlite:// DATABASE_URL or set DATABASE_URL accordingly. "
            "TODO: implement with psycopg3 or asyncpg."
        )

    # SessionRepository

    def create_session(self, *, session_id: str, goal: str, plan: list[str], artifacts: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def list_sessions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def update_session_artifacts(self, session_id: str, artifacts: dict[str, Any]) -> None:
        raise NotImplementedError

    # RunRepository

    def create_run(self, *, run_id: str, session_id: str, status: str, run_type: str, current_state: str, trigger_message: str, results: list[dict[str, Any]], steps: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    def update_run(self, *, run_id: str, status: str, current_state: str, results: list[dict[str, Any]], steps: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    def list_runs(self, session_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_run_steps(self, run_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    # MessageRepository

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def append_messages(self, session_id: str, run_id: str, history: Iterable[dict[str, str]]) -> None:
        raise NotImplementedError


class PostgresPlanStore:
    """Postgres-backed plan store (not yet implemented).

    TODO: Implement with psycopg3 or asyncpg.
    """

    def __init__(self, db_path: Optional[Path] = None, database_url: str = "") -> None:
        raise NotImplementedError(
            "PostgresPlanStore is not yet implemented. "
            "TODO: implement with psycopg3 or asyncpg."
        )

    def upsert_plan(self, session_id: str, steps: list[str]) -> None:
        raise NotImplementedError

    def get_plan(self, session_id: str) -> Optional[PlanDocument]:
        raise NotImplementedError

    def set_status(self, session_id: str, status: str) -> None:
        raise NotImplementedError

    def approve(self, session_id: str, actor: str, note: str = "") -> None:
        raise NotImplementedError

    def reject(self, session_id: str, actor: str, note: str = "") -> None:
        raise NotImplementedError

    def list_plans(self) -> list[PlanDocument]:
        raise NotImplementedError

    def list_approvals(self, session_id: str) -> list[ApprovalRecord]:
        raise NotImplementedError


__all__ = ["PostgresPlanStore", "PostgresStore"]
