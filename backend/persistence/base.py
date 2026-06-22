"""Repository protocol definitions for the persistence layer.

All concrete stores (SQLite, Postgres, …) must satisfy these structural
sub-types.  Protocols are runtime-checkable so ``isinstance`` guards work.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Protocol, runtime_checkable

from backend.plans.models import ApprovalRecord, PlanDocument


@runtime_checkable
class SessionRepository(Protocol):
    def create_session(
        self,
        *,
        session_id: str,
        goal: str,
        plan: list[str],
        artifacts: dict[str, Any],
    ) -> None: ...

    def get_session(self, session_id: str) -> dict[str, Any] | None: ...

    def list_sessions(self) -> list[dict[str, Any]]: ...

    def update_session_artifacts(
        self, session_id: str, artifacts: dict[str, Any]
    ) -> None: ...


@runtime_checkable
class RunRepository(Protocol):
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
    ) -> None: ...

    def update_run(
        self,
        *,
        run_id: str,
        status: str,
        current_state: str,
        results: list[dict[str, Any]],
        steps: list[dict[str, Any]],
    ) -> None: ...

    def list_runs(self, session_id: str) -> list[dict[str, Any]]: ...

    def list_run_steps(self, run_id: str) -> list[dict[str, Any]]: ...


@runtime_checkable
class MessageRepository(Protocol):
    def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...

    def append_messages(
        self,
        session_id: str,
        run_id: str,
        history: Iterable[dict[str, str]],
    ) -> None: ...


@runtime_checkable
class PlanRepository(Protocol):
    def upsert_plan(self, session_id: str, steps: list[str]) -> None: ...

    def get_plan(self, session_id: str) -> Optional[PlanDocument]: ...

    def set_status(self, session_id: str, status: str) -> None: ...

    def approve(self, session_id: str, actor: str, note: str = "") -> None: ...

    def reject(self, session_id: str, actor: str, note: str = "") -> None: ...

    def list_plans(self) -> list[PlanDocument]: ...

    def list_approvals(self, session_id: str) -> list[ApprovalRecord]: ...


__all__ = [
    "MessageRepository",
    "PlanRepository",
    "RunRepository",
    "SessionRepository",
]
