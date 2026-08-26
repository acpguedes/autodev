"""Real multi-connection PostgreSQL concurrency proof for PolicyStore (E53-S2).

Every test here opens genuinely independent connections against a real
PostgreSQL database (threads racing the same pending decision), so the
invariant is shown to come from the database's own row-level locking on the
state-guarded conditional ``UPDATE`` -- not from anything held in one Python
process -- the same proof shape
``backend/tests/unit/quotas/test_postgres_concurrency.py`` (E51-S4) and
``backend/tests/unit/secret_store/test_postgres_concurrency.py`` (E52-S2)
established. Skips automatically unless ``AUTODEV_TEST_POSTGRES_URL`` is
set; CI wiring for a real PostgreSQL service lands in E57.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.execution.contracts import ExecutionAction, ExecutionActionType
from backend.execution.decisions import DecisionAlreadyResolvedError, DecisionService
from backend.execution.policy import DecisionStatus, PolicyCategory

_POSTGRES_URL = os.environ.get("AUTODEV_TEST_POSTGRES_URL", "")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not _POSTGRES_URL, reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E53)"
    ),
]


def _store():
    """Build a fresh :class:`PolicyStore` over its own PostgreSQL connection."""
    from backend.execution.policy import PolicyStore
    from backend.persistence.postgres_adapter import PostgresStore

    return PolicyStore(store=PostgresStore(_POSTGRES_URL))


def _tenant() -> str:
    """A fresh, collision-free tenant id for one test's isolated slice of the shared database."""
    import uuid

    return f"e53-concurrency-{uuid.uuid4().hex}"


def _action(action_id: str = "a1") -> ExecutionAction:
    return ExecutionAction(
        action_id=action_id,
        type=ExecutionActionType.RUN_COMMAND,
        task_id="task-1",
        step_key="task-1",
        command=["pytest"],
    )


def test_concurrent_approve_and_reject_leave_exactly_one_terminal_state() -> None:
    """16 threads race approve/reject against a real PostgreSQL -- exactly one outcome sticks (E53-S2-T2)."""
    tenant_id = _tenant()
    service = DecisionService(store=_store())
    pending = service.request(
        tenant_id=tenant_id,
        run_id=f"{tenant_id}-run",
        task_id="task-1",
        action=_action(),
        category=PolicyCategory.SHELL,
        prompt="run pytest?",
    )
    attempts = 16

    def _resolve(index: int) -> DecisionStatus | None:
        outcome = DecisionStatus.APPROVED if index % 2 == 0 else DecisionStatus.DENIED
        service_for_thread = DecisionService(store=_store())
        try:
            resolved = service_for_thread.resolve(
                pending.decision_id, tenant_id=tenant_id, decision=outcome, actor=f"racer-{index}"
            )
            return resolved.status
        except DecisionAlreadyResolvedError:
            return None

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(pool.map(_resolve, range(attempts)))

    winning_statuses = {status for status in outcomes if status is not None}
    assert len(winning_statuses) == 1, "every racer that saw a resolved decision saw the same one"

    final = _store().get_pending_decision(pending.decision_id, tenant_id=tenant_id)
    assert final is not None
    assert final.status in (DecisionStatus.APPROVED, DecisionStatus.DENIED)


def test_replaying_the_same_decision_and_outcome_is_idempotent_under_real_postgres() -> None:
    """8 threads replay the exact same (decision_id, outcome) pair -- one recorded result, no error (E53-S2-T3)."""
    tenant_id = _tenant()
    service = DecisionService(store=_store())
    pending = service.request(
        tenant_id=tenant_id,
        run_id=f"{tenant_id}-run",
        task_id="task-1",
        action=_action(),
        category=PolicyCategory.SHELL,
        prompt="run pytest?",
    )
    attempts = 8

    def _approve(index: int) -> str:
        service_for_thread = DecisionService(store=_store())
        resolved = service_for_thread.resolve(
            pending.decision_id,
            tenant_id=tenant_id,
            decision=DecisionStatus.APPROVED,
            actor=f"racer-{index}",
        )
        return resolved.decided_at or ""

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        decided_ats = list(pool.map(_approve, range(attempts)))

    assert len(set(decided_ats)) == 1, "every replay observes the same recorded decided_at"
