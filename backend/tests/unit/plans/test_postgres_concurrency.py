"""Real multi-connection PostgreSQL concurrency proof for StepApprovalStore (E55-S2).

Every test here opens genuinely independent connections against a real
PostgreSQL database (threads racing the same step's transition), so the
"exactly one replica can move a step out of ``under_review``" invariant is
shown to come from the database's row locking and the state-guarded
conditional update, not from anything held in one Python process -- the
same proof shape ``backend/tests/unit/quotas/test_postgres_concurrency.py``
(E51-S4) and ``backend/tests/unit/secret_store/test_postgres_concurrency.py``
(E52-S2) established for their stores. Skips automatically unless
``AUTODEV_TEST_POSTGRES_URL`` is set; CI wiring for a real PostgreSQL service
lands in E57.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

_POSTGRES_URL = os.environ.get("AUTODEV_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_URL, reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E55)"
)


def _postgres_store():
    """Build a fresh :class:`~backend.persistence.postgres_adapter.PostgresStore`."""
    from backend.persistence.postgres_adapter import PostgresStore

    return PostgresStore(_POSTGRES_URL)


def _step_store():
    """Build a fresh :class:`StepApprovalStore` over its own PostgreSQL connection."""
    from backend.plans.step_state import StepApprovalStore

    return StepApprovalStore(store=_postgres_store())


def _seeded_session() -> tuple[str, str]:
    """Create a fresh ``plan_documents`` row (the FK parent) and one tracked step.

    Returns:
        A ``(tenant_id, session_id)`` pair unique to this test.
    """
    import uuid

    from backend.persistence.postgres_adapter.plan_store import PostgresPlanStore

    tenant_id = f"e55-concurrency-{uuid.uuid4().hex}"
    session_id = f"session-{uuid.uuid4().hex}"
    PostgresPlanStore(database_url=_POSTGRES_URL).upsert_plan(
        session_id, ["Step under test"], tenant_id=tenant_id
    )
    _step_store().ensure_steps(session_id, ["Step under test"], tenant_id=tenant_id)
    return tenant_id, session_id


def test_concurrent_transitions_out_of_under_review_yield_exactly_one_winner() -> None:
    """16 threads race to approve/reject the same step -- exactly one transition wins (E55-S2-T2)."""
    tenant_id, session_id = _seeded_session()
    _step_store().transition(session_id, 0, "review", tenant_id=tenant_id)
    attempts = 16

    def _race(index: int) -> str | None:
        action = "approve" if index % 2 == 0 else "reject"
        try:
            _, record = _step_store().transition(session_id, 0, action, tenant_id=tenant_id)
            return record.state.value
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(pool.map(_race, range(attempts)))

    winners = [outcome for outcome in outcomes if outcome is not None]
    assert len(winners) == 1, "exactly one racing transition succeeds"
    assert winners[0] in {"approved", "rejected"}

    final = _step_store().get_step(session_id, 0, tenant_id=tenant_id)
    assert final is not None
    assert final.state.value == winners[0], "the persisted state matches the one reported winner"


def test_concurrent_content_edits_after_a_transition_reject_the_loser() -> None:
    """A content edit racing an approval either wins cleanly or is rejected, never silently lost (E55-S2-T3)."""
    tenant_id, session_id = _seeded_session()
    _step_store().transition(session_id, 0, "review", tenant_id=tenant_id)

    def _approve() -> None:
        _step_store().transition(session_id, 0, "approve", tenant_id=tenant_id)

    def _edit() -> bool:
        try:
            _step_store().update_content(session_id, 0, "raced edit", tenant_id=tenant_id)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        approve_future = pool.submit(_approve)
        edit_future = pool.submit(_edit)
        approve_future.result()
        edit_succeeded = edit_future.result()

    final = _step_store().get_step(session_id, 0, tenant_id=tenant_id)
    assert final is not None
    assert final.state.value == "approved"
    if edit_succeeded:
        assert final.content == "raced edit"
    else:
        assert final.content == "Step under test"
