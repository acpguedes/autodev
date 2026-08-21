"""Pure codec helpers shared by the SQLite and Postgres persistence adapters.

Row/document shaping, timestamp handling, and per-attempt batch preparation
that is identical between the two backends lives here (E47-S4). SQL text —
placeholder style, upsert dialect, RLS — stays adapter-specific by design;
this module intentionally contains no SQL and no backend branching. See
``docs/v2_platform/phases/e47_backend_structural_consolidation.md`` (E47-S4).
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Iterable


def dumps_json(value: Any) -> str:
    """Serialize a value to a JSON string."""
    return json.dumps(value)


def loads_json(value: Any) -> Any:
    """Deserialize a JSON string, passing non-string values through unchanged.

    SQLite's TEXT columns always come back as ``str``. Postgres's JSONB
    columns may already be decoded by the driver before this ever runs; this
    passthrough is the safe superset for both.
    """
    if isinstance(value, str):
        return json.loads(value)
    return value


def utcnow_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def build_session_record(
    *,
    id: str,
    goal: str,
    plan: Any,
    artifacts: Any,
    created_at: Any,
    updated_at: Any,
) -> dict[str, Any]:
    """Build the store's public ``sessions`` dict shape from normalized scalars."""
    return {
        "id": id,
        "goal": goal,
        "plan": plan,
        "artifacts": artifacts,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def build_run_record(
    *,
    id: str,
    session_id: str,
    status: str,
    run_type: str,
    current_state: str,
    trigger_message: str,
    results: Any,
    steps: list[dict[str, Any]],
    created_at: Any,
    completed_at: Any,
) -> dict[str, Any]:
    """Build the store's public ``runs`` dict shape from normalized scalars.

    ``steps`` is passed in already fetched and decoded, so this stays pure —
    it never issues a query or opens a connection of its own (E44-S1).
    """
    return {
        "id": id,
        "session_id": session_id,
        "status": status,
        "run_type": run_type,
        "current_state": current_state,
        "trigger_message": trigger_message,
        "results": results,
        "steps": steps,
        "created_at": created_at,
        "completed_at": completed_at,
    }


def build_step_record(
    *,
    step_key: str,
    agent: str,
    status: str,
    started_at: Any,
    completed_at: Any,
    attempt: Any,
) -> dict[str, Any]:
    """Build the store's public ``run_steps`` dict shape."""
    return {
        "step_key": step_key,
        "agent": agent,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "attempt": attempt,
    }


def group_steps_by_run(
    rows: Iterable[tuple[str, dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Group already-decoded ``(run_id, step_record)`` pairs by run id.

    Preserves the input order within each run's step list. Runs with no
    steps are absent from the result (E44-S1).
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run_id, step in rows:
        grouped.setdefault(run_id, []).append(step)
    return grouped


def prepare_step_batch(run_id: str, steps: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Build the ``executemany`` parameter batch for a run's step upsert (E44-S2).

    Column order — ``(run_id, position, step_key, agent, status, started_at,
    completed_at, attempt)`` — is identical for both backends' upsert
    statements; only the SQL text (placeholders, ``ON CONFLICT`` dialect)
    differs per adapter.
    """
    return [
        (
            run_id,
            position,
            step["step_key"],
            step["agent"],
            step["status"],
            step["started_at"],
            step["completed_at"],
            step.get("attempt", 1),
        )
        for position, step in enumerate(steps)
    ]


def build_promotion_record(
    *,
    policy_id: str,
    snapshot_id: str,
    baseline_snapshot_id: str,
    promoted: Any,
    reason: str,
    decided_at: Any,
) -> dict[str, Any]:
    """Build the store's public score-snapshot-promotion dict shape (camelCase, API-facing).

    ``promoted`` is unconditionally coerced with ``bool()``: SQLite stores it
    as a 0/1 integer, Postgres returns a real ``bool`` — the cast is a no-op
    for the latter and correct for the former.
    """
    return {
        "policyId": policy_id,
        "snapshotId": snapshot_id,
        "baselineSnapshotId": baseline_snapshot_id,
        "promoted": bool(promoted),
        "reason": reason,
        "decidedAt": decided_at,
    }


__all__ = [
    "build_promotion_record",
    "build_run_record",
    "build_session_record",
    "build_step_record",
    "dumps_json",
    "group_steps_by_run",
    "loads_json",
    "prepare_step_batch",
    "utcnow_iso",
]
