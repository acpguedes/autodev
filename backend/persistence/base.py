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


@runtime_checkable
class EvalResultRepository(Protocol):
    """Durable storage for immutable, versioned Evaluation Service (E5-S3) results."""

    def create_eval_result(
        self, *, eval_id: str, eval_version: str, run_id: str, document: dict[str, Any]
    ) -> None: ...

    def get_eval_result(self, eval_id: str, eval_version: str, run_id: str) -> dict[str, Any] | None: ...

    def list_eval_results(self, eval_id: str, eval_version: str | None = None) -> list[dict[str, Any]]: ...


@runtime_checkable
class ScoreSnapshotRepository(Protocol):
    """Durable storage for the Router/Selector closed feedback loop (E5-S4).

    Two independent record kinds: an immutable, versioned
    :class:`~backend.routing.contract.ScoreSnapshot` published by the
    Evaluation Service (never overwritten, mirroring ``eval_results``'
    immutability convention from ADR-009), and an append-only audit log of
    every promotion *decision* (promoted or blocked) a
    :class:`~backend.routing.feedback.RoutingFeedbackService` makes against a
    routing policy id — recorded even when a snapshot is *not* promoted, so a
    regression is auditable rather than silent (reference §9.5).
    """

    def create_score_snapshot(
        self, *, snapshot_id: str, sample_count: int, document: dict[str, Any]
    ) -> None:
        """Persist one immutable, versioned score snapshot document."""
        ...

    def get_score_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Fetch one persisted score snapshot document, or ``None`` if it does not exist."""
        ...

    def list_score_snapshots(self, limit: int = 50) -> list[dict[str, Any]]:
        """List persisted score snapshots, newest first."""
        ...

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
        """Append one promotion decision (promoted or blocked) to the audit log."""
        ...

    def get_active_score_snapshot(self, policy_id: str) -> dict[str, Any] | None:
        """Fetch the currently promoted snapshot document for a policy id, or ``None``."""
        ...

    def list_snapshot_promotions(self, policy_id: str) -> list[dict[str, Any]]:
        """List every promotion decision recorded for a policy id, newest first."""
        ...


__all__ = [
    "EvalResultRepository",
    "MessageRepository",
    "PlanRepository",
    "RunRepository",
    "ScoreSnapshotRepository",
    "SessionRepository",
]
