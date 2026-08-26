"""Tests for the decision audit trail and atomic terminal transition (E53-S2)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.execution.contracts import ExecutionAction, ExecutionActionType
from backend.execution.decisions import DecisionAlreadyResolvedError, DecisionService
from backend.execution.policy import DecisionStatus, PolicyCategory, PolicyStore


def _store(tmp_path: Path) -> PolicyStore:
    return PolicyStore(db_path=tmp_path / "policy.db")


def _action(action_id: str = "a1") -> ExecutionAction:
    return ExecutionAction(
        action_id=action_id,
        type=ExecutionActionType.RUN_COMMAND,
        task_id="task-1",
        step_key="task-1",
        command=["pytest"],
    )


def _request(service: DecisionService, *, tenant_id: str = "acme"):
    return service.request(
        tenant_id=tenant_id,
        run_id="run-1",
        task_id="task-1",
        action=_action(),
        category=PolicyCategory.SHELL,
        prompt="run pytest?",
    )


def test_resolve_is_idempotent_on_replay_with_the_same_outcome(tmp_path: Path) -> None:
    """Replaying the same decision with the same outcome returns the recorded result (E53-S2-T3)."""
    service = DecisionService(store=_store(tmp_path))
    pending = _request(service)

    first = service.resolve(
        pending.decision_id, tenant_id="acme", decision=DecisionStatus.APPROVED, actor="tester"
    )
    second = service.resolve(
        pending.decision_id, tenant_id="acme", decision=DecisionStatus.APPROVED, actor="tester-retry"
    )

    assert first.status is DecisionStatus.APPROVED
    assert second.status is DecisionStatus.APPROVED
    assert second.decided_at == first.decided_at
    assert second.decided_by == first.decided_by


def test_resolve_raises_on_replay_with_a_different_outcome(tmp_path: Path) -> None:
    """Replaying with a conflicting outcome still raises -- no silent overwrite (E53-S2-T2)."""
    service = DecisionService(store=_store(tmp_path))
    pending = _request(service)
    service.resolve(pending.decision_id, tenant_id="acme", decision=DecisionStatus.APPROVED, actor="tester")

    with pytest.raises(DecisionAlreadyResolvedError):
        service.resolve(pending.decision_id, tenant_id="acme", decision=DecisionStatus.DENIED, actor="other")


def test_concurrent_approve_and_reject_leave_exactly_one_terminal_state(tmp_path: Path) -> None:
    """16 threads race approve/reject on the same pending decision -- exactly one wins (E53-S2-T2)."""
    store = _store(tmp_path)
    service = DecisionService(store=store)
    pending = _request(service)
    attempts = 16

    def _resolve(index: int) -> DecisionStatus | None:
        outcome = DecisionStatus.APPROVED if index % 2 == 0 else DecisionStatus.DENIED
        try:
            resolved = service.resolve(
                pending.decision_id, tenant_id="acme", decision=outcome, actor=f"racer-{index}"
            )
            return resolved.status
        except DecisionAlreadyResolvedError:
            return None

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(pool.map(_resolve, range(attempts)))

    winning_statuses = {status for status in outcomes if status is not None}
    assert winning_statuses, "at least one racer must observe (or itself record) a terminal state"
    assert len(winning_statuses) == 1, "every racer that saw a resolved decision saw the same one"

    final = store.get_pending_decision(pending.decision_id, tenant_id="acme")
    assert final is not None
    assert final.status is not DecisionStatus.PENDING
    assert final.status in (DecisionStatus.APPROVED, DecisionStatus.DENIED)
