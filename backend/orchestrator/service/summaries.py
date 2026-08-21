"""Session/run summary building for the orchestrator's read-side API (E47-S5-T4)."""

from __future__ import annotations

from typing import Any

from backend.orchestrator.service.models import (
    AgentExecution,
    HistoryItem,
    RunStatus,
    RunStep,
    RunSummary,
    SessionSummary,
)
from backend.persistence.tenancy import DEFAULT_TENANT_ID


def build_session_summary(
    store: Any, record: dict[str, Any], *, tenant_id: str = DEFAULT_TENANT_ID
) -> SessionSummary:
    """Build a :class:`~backend.orchestrator.service.models.SessionSummary` from a raw store session record."""
    messages = store.list_messages(record["id"], tenant_id=tenant_id)
    history = [HistoryItem(role=item["role"], content=item["content"]) for item in messages]
    last_activity = str(messages[-1]["created_at"]) if messages else None
    return SessionSummary(
        session_id=record["id"],
        goal=record["goal"],
        plan=list(record["plan"] or []),
        status=RunStatus.AWAITING_INPUT,
        history=history,
        message_count=len(history),
        last_activity=last_activity,
    )


def build_run_summary(record: dict[str, Any]) -> RunSummary:
    """Build a :class:`~backend.orchestrator.service.models.RunSummary` from a raw store run record."""
    results = [
        AgentExecution(
            agent=item.get("agent", "unknown"),
            content=item.get("content", ""),
            metadata=item.get("metadata", {}),
        )
        for item in (record["results"] or [])
    ]
    return RunSummary(
        run_id=record["id"],
        session_id=record["session_id"],
        status=record["status"],
        run_type=record["run_type"],
        current_state=record["current_state"],
        trigger_message=record["trigger_message"],
        created_at=record["created_at"],
        results=results,
        steps=[
            RunStep(
                step_key=item["step_key"],
                agent=item["agent"],
                status=item["status"],
                started_at=item["started_at"],
                completed_at=item["completed_at"],
                attempt=item.get("attempt", 1),
            )
            for item in (record["steps"] or [])
        ],
    )


__all__ = ["build_run_summary", "build_session_summary"]
