"""Direct unit tests for :class:`StepApprovalStore` (E55-S1/S2).

Exercises the store below the ``/v2`` API surface: the state-machine's
illegal transitions/edits/deletes (E55-S2-T3, mirroring E16-S2-T3's original
proof but now against the ported, tenant-scoped store), unknown-step errors,
and tenant isolation on ``plan_step_state`` (the security requirement E55's
phase doc calls out — a step tracked under one tenant must be invisible to
another).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.plans.step_state import (
    EDITABLE_STATES,
    REMOVABLE_STATES,
    StepApprovalStore,
    StepState,
)


@pytest.fixture()
def store(tmp_path: Path) -> StepApprovalStore:
    """A store over a dedicated SQLite file, independent of any other test."""
    return StepApprovalStore(db_path=tmp_path / "step-state.db")


def _seed(store: StepApprovalStore, session_id: str = "s1", tenant_id: str = "default") -> None:
    store.ensure_steps(session_id, ["Do the thing"], tenant_id=tenant_id)


class TestUnknownStep:
    """Every mutating method raises KeyError for an untracked step."""

    def test_update_content_unknown_step_raises_keyerror(self, store: StepApprovalStore) -> None:
        _seed(store)
        with pytest.raises(KeyError):
            store.update_content("s1", 5, "new content")

    def test_delete_step_unknown_step_raises_keyerror(self, store: StepApprovalStore) -> None:
        _seed(store)
        with pytest.raises(KeyError):
            store.delete_step("s1", 5)

    def test_transition_unknown_step_raises_keyerror(self, store: StepApprovalStore) -> None:
        _seed(store)
        with pytest.raises(KeyError):
            store.transition("s1", 5, "review")

    def test_get_step_unknown_step_returns_none(self, store: StepApprovalStore) -> None:
        _seed(store)
        assert store.get_step("s1", 5) is None


class TestIllegalTransitions:
    """Every action illegal from a given state is rejected (E55-S2-T2/T3)."""

    @pytest.mark.parametrize(
        "state,action",
        [
            (StepState.DRAFT, "approve"),
            (StepState.DRAFT, "reject"),
            (StepState.DRAFT, "execute"),
            (StepState.DRAFT, "complete"),
            (StepState.UNDER_REVIEW, "execute"),
            (StepState.UNDER_REVIEW, "complete"),
            (StepState.UNDER_REVIEW, "review"),
            (StepState.APPROVED, "approve"),
            (StepState.APPROVED, "reject"),
            (StepState.APPROVED, "complete"),
            (StepState.APPROVED, "review"),
            (StepState.REJECTED, "approve"),
            (StepState.REJECTED, "reject"),
            (StepState.REJECTED, "execute"),
            (StepState.REJECTED, "complete"),
            (StepState.REJECTED, "review"),
            (StepState.EXECUTING, "review"),
            (StepState.EXECUTING, "approve"),
            (StepState.EXECUTING, "reject"),
            (StepState.EXECUTING, "execute"),
            (StepState.COMPLETED, "review"),
            (StepState.COMPLETED, "approve"),
            (StepState.COMPLETED, "reject"),
            (StepState.COMPLETED, "execute"),
            (StepState.COMPLETED, "complete"),
        ],
    )
    def test_illegal_transition_is_rejected(
        self, store: StepApprovalStore, state: StepState, action: str
    ) -> None:
        _seed(store)
        _drive_to_state(store, "s1", 0, state)
        with pytest.raises(ValueError):
            store.transition("s1", 0, action)

    @pytest.mark.parametrize(
        "action,expected",
        [
            ("review", StepState.UNDER_REVIEW),
            ("approve", None),  # legal only after "review"
        ],
    )
    def test_legal_transition_from_draft(
        self, store: StepApprovalStore, action: str, expected: StepState | None
    ) -> None:
        _seed(store)
        if expected is None:
            with pytest.raises(ValueError):
                store.transition("s1", 0, action)
            return
        _previous, record = store.transition("s1", 0, action)
        assert record.state is expected


def _drive_to_state(store: StepApprovalStore, session_id: str, step_index: int, target: StepState) -> None:
    """Walk a freshly-seeded (``draft``) step forward to *target* via legal transitions."""
    path: dict[StepState, list[str]] = {
        StepState.DRAFT: [],
        StepState.UNDER_REVIEW: ["review"],
        StepState.APPROVED: ["review", "approve"],
        StepState.REJECTED: ["review", "reject"],
        StepState.EXECUTING: ["review", "approve", "execute"],
        StepState.COMPLETED: ["review", "approve", "execute", "complete"],
    }
    for action in path[target]:
        store.transition(session_id, step_index, action)


class TestIllegalEditsAndDeletes:
    """Edits/deletes are rejected outside EDITABLE_STATES/REMOVABLE_STATES (E55-S2-T3)."""

    @pytest.mark.parametrize(
        "state",
        [s for s in StepState if s not in EDITABLE_STATES],
    )
    def test_update_content_rejected_outside_editable_states(
        self, store: StepApprovalStore, state: StepState
    ) -> None:
        _seed(store)
        _drive_to_state(store, "s1", 0, state)
        with pytest.raises(ValueError):
            store.update_content("s1", 0, "attempted edit")

    @pytest.mark.parametrize(
        "state",
        [s for s in StepState if s in EDITABLE_STATES],
    )
    def test_update_content_allowed_inside_editable_states(
        self, store: StepApprovalStore, state: StepState
    ) -> None:
        _seed(store)
        _drive_to_state(store, "s1", 0, state)
        record = store.update_content("s1", 0, "allowed edit")
        assert record.content == "allowed edit"

    @pytest.mark.parametrize(
        "state",
        [s for s in StepState if s not in REMOVABLE_STATES],
    )
    def test_delete_step_rejected_outside_removable_states(
        self, store: StepApprovalStore, state: StepState
    ) -> None:
        _seed(store)
        _drive_to_state(store, "s1", 0, state)
        with pytest.raises(ValueError):
            store.delete_step("s1", 0)

    @pytest.mark.parametrize(
        "state",
        [s for s in StepState if s in REMOVABLE_STATES],
    )
    def test_delete_step_allowed_inside_removable_states(
        self, store: StepApprovalStore, state: StepState
    ) -> None:
        _seed(store)
        _drive_to_state(store, "s1", 0, state)
        remaining = store.delete_step("s1", 0)
        assert remaining == []


class TestTenantIsolation:
    """A step tracked under one tenant is invisible under another (E55 security)."""

    def test_list_steps_is_scoped_to_tenant(self, store: StepApprovalStore) -> None:
        store.ensure_steps("shared-session", ["Tenant A's step"], tenant_id="tenant-a")
        assert store.list_steps("shared-session", tenant_id="tenant-a") != []
        assert store.list_steps("shared-session", tenant_id="tenant-b") == []

    def test_get_step_is_scoped_to_tenant(self, store: StepApprovalStore) -> None:
        store.ensure_steps("shared-session", ["Tenant A's step"], tenant_id="tenant-a")
        assert store.get_step("shared-session", 0, tenant_id="tenant-a") is not None
        assert store.get_step("shared-session", 0, tenant_id="tenant-b") is None

    def test_transition_does_not_cross_tenants(self, store: StepApprovalStore) -> None:
        store.ensure_steps("shared-session", ["Tenant A's step"], tenant_id="tenant-a")
        with pytest.raises(KeyError):
            store.transition("shared-session", 0, "review", tenant_id="tenant-b")
        # Untouched under its own tenant.
        record = store.get_step("shared-session", 0, tenant_id="tenant-a")
        assert record is not None
        assert record.state is StepState.DRAFT
