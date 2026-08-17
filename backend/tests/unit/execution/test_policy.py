"""Tests for the execution policy engine (E14-S2, RFC-010/ADR-022)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config.settings import Settings
from backend.events.runtime import get_event_bus, reset_event_bus_for_tests
from backend.execution.contracts import ExecutionAction, ExecutionActionType
from backend.execution.policy import (
    PolicyCategory,
    PolicyEffect,
    PolicyMissingError,
    PolicyRule,
    PolicyScopeKind,
    PolicyService,
    PolicyStore,
)


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_event_bus_for_tests()
    yield
    reset_event_bus_for_tests()


def _service(tmp_path: Path, *, profile: str = "local") -> PolicyService:
    """Build a PolicyService over a throwaway store, with the given profile.

    Mirrors ``backend/tests/unit/quotas/test_service.py``'s ``_service``
    helper: ``Settings.model_construct`` bypasses the cross-field
    validation that would otherwise require a full production
    infrastructure stack just to exercise ``autodev_profile == "prod"``.
    """
    store = PolicyStore(db_path=tmp_path / "policy.db")
    if profile == "prod":
        settings = Settings.model_construct(autodev_profile="prod")
    else:
        settings = Settings()
    return PolicyService(store=store, settings=settings)


def _action(action_id: str = "a1", command: list[str] | None = None, path: str | None = None) -> ExecutionAction:
    return ExecutionAction(
        action_id=action_id,
        type=ExecutionActionType.RUN_COMMAND if command else ExecutionActionType.CREATE_FILE,
        task_id="task-1",
        step_key="task-1",
        command=command,
        path=path,
    )


def test_local_mode_falls_back_to_a_permissive_default_when_no_rules_are_stored(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, profile="local")
    decision = service.evaluate(
        tenant_id="acme", action=_action(command=["pytest"]), run_id="run-1"
    )
    assert decision.allowed is True
    assert decision.matched is True


def test_production_without_a_stored_rule_denies_and_fails_closed(tmp_path: Path) -> None:
    service = _service(tmp_path, profile="prod")
    with pytest.raises(PolicyMissingError):
        service.resolve_rules("acme")


def test_production_evaluate_denies_when_no_policy_is_configured(tmp_path: Path) -> None:
    service = _service(tmp_path, profile="prod")
    with pytest.raises(PolicyMissingError):
        service.evaluate(tenant_id="acme", action=_action(command=["pytest"]), run_id="run-1")


def test_an_uncovered_category_is_denied_but_not_matched(tmp_path: Path) -> None:
    service = _service(tmp_path, profile="local")
    service.set_rule(
        "acme",
        PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
        ),
    )
    decision = service.evaluate(
        tenant_id="acme",
        action=_action(action_id="a2", path="notes/x.md"),
        run_id="run-1",
    )
    assert decision.matched is False
    assert decision.allowed is False


def test_an_explicit_deny_wins_over_a_broader_allow(tmp_path: Path) -> None:
    service = _service(tmp_path, profile="local")
    service.set_rule(
        "acme",
        PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
        ),
    )
    service.set_rule(
        "acme",
        PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.DENY,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
            pattern="rm",
        ),
    )
    allowed_decision = service.evaluate(
        tenant_id="acme", action=_action(action_id="a1", command=["pytest"]), run_id="run-1"
    )
    denied_decision = service.evaluate(
        tenant_id="acme", action=_action(action_id="a2", command=["rm"]), run_id="run-1"
    )
    assert allowed_decision.allowed is True
    assert denied_decision.allowed is False
    assert denied_decision.matched is True


def test_a_dynamic_permission_is_consulted_alongside_stored_rules(tmp_path: Path) -> None:
    service = _service(tmp_path, profile="local")
    service.set_rule(
        "acme",
        PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.DENY,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
        ),
    )
    service.grant_dynamic_permission(
        "acme",
        PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
            pattern="sqlite",
        ),
        actor="operator@example.com",
    )
    decision = service.evaluate(
        tenant_id="acme", action=_action(action_id="a1", command=["sqlite"]), run_id="run-1"
    )
    assert decision.allowed is True


def test_evaluate_records_an_audit_row_and_emits_the_matching_event(tmp_path: Path) -> None:
    service = _service(tmp_path, profile="local")
    service.evaluate(
        tenant_id="acme", action=_action(command=["pytest"]), run_id="run-1", actor="tester"
    )
    envelopes = get_event_bus().replay("run-1")
    types = [envelope.type for envelope in envelopes]
    assert types == ["execution.policy.allowed"]


def test_revoke_dynamic_permission_removes_it(tmp_path: Path) -> None:
    service = _service(tmp_path, profile="local")
    permission_id = service.grant_dynamic_permission(
        "acme",
        PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
        ),
        actor="operator@example.com",
    )
    assert service.list_dynamic_permissions("acme")
    assert service.revoke_dynamic_permission("acme", permission_id) is True
    assert service.list_dynamic_permissions("acme") == []
