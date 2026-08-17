"""Tests for execution modes (E14-S3): approval, auto, hybrid, timeout, resume."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.execution.decisions import DecisionService
from backend.execution.modes import ExecutionMode
from backend.execution.policy import (
    DecisionStatus,
    PolicyCategory,
    PolicyEffect,
    PolicyRule,
    PolicyScopeKind,
    PolicyService,
    PolicyStore,
)
from backend.orchestrator.service import ExecutionTask, OrchestratorService, RunStatus, StepStatus
from backend.persistence import DurableStore
from backend.persistence.tenancy import DEFAULT_TENANT_ID


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _build_orchestrator(
    tmp_path: Path, *, policy_service: PolicyService | None = None, decision_service: DecisionService | None = None
) -> OrchestratorService:
    """Build an isolated orchestrator, always over a tmp_path-scoped policy store.

    Never falls through to the default ``./autodev.db``-backed
    ``PolicyService()``/``DecisionService()`` — this module's tests list
    pending decisions per tenant, which would leak across tests sharing the
    ambient default store (the same reason quota tests always pass an
    explicit ``db_path``).
    """
    _write(tmp_path / "frontend" / "app" / "page.tsx", "export default function Page() { return null; }")
    _write(tmp_path / "backend" / "api" / "main.py", "from fastapi import FastAPI")
    store = DurableStore(f"sqlite:///{tmp_path / 'autodev-test.db'}")
    if policy_service is None:
        policy_service = PolicyService(store=PolicyStore(db_path=tmp_path / "policy.db"))
    if decision_service is None:
        decision_service = DecisionService(store=PolicyStore(db_path=tmp_path / "policy.db"))
    return OrchestratorService(
        store=store,
        project_root=tmp_path,
        policy_service=policy_service,
        decision_service=decision_service,
    )


def _start_session(orchestrator: OrchestratorService) -> str:
    session = orchestrator.create_plan("Criar plano executável por tarefas")
    orchestrator.handle_message(session.session_id, "produza análise e checklist de implementação")
    return session.session_id


def test_approval_mode_pauses_at_the_first_task_with_an_action(tmp_path: Path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    session_id = _start_session(orchestrator)

    run = orchestrator.execute_plan(session_id, mode=ExecutionMode.APPROVAL)

    assert run.status == RunStatus.AWAITING_APPROVAL
    paused_steps = [step for step in run.steps if step.status == StepStatus.AWAITING_APPROVAL]
    assert len(paused_steps) == 1
    assert paused_steps[0].step_key.startswith("coding-")
    assert all(step.status == StepStatus.COMPLETED for step in run.steps[:-1])


def test_approval_mode_lists_the_pending_decision(tmp_path: Path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    session_id = _start_session(orchestrator)
    orchestrator.execute_plan(session_id, mode=ExecutionMode.APPROVAL)

    pending = orchestrator.list_pending_execution_decisions(tenant_id=DEFAULT_TENANT_ID)

    assert len(pending) == 1
    assert pending[0].status == DecisionStatus.PENDING
    assert pending[0].task_id.startswith("coding-")


def test_approval_mode_resume_until_completion_after_approving_every_decision(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    orchestrator = _build_orchestrator(tmp_path)
    session_id = _start_session(orchestrator)
    run = orchestrator.execute_plan(session_id, mode=ExecutionMode.APPROVAL)

    guard = 0
    while run.status == RunStatus.AWAITING_APPROVAL and guard < 20:
        pending = orchestrator.list_pending_execution_decisions(tenant_id=DEFAULT_TENANT_ID)
        assert pending
        orchestrator.resolve_execution_decision(
            pending[0].decision_id, tenant_id=DEFAULT_TENANT_ID, decision="approve", actor="tester"
        )
        run = orchestrator.resume_plan_execution(session_id, run.run_id, mode=ExecutionMode.APPROVAL)
        guard += 1

    assert run.status == RunStatus.COMPLETED
    assert all(step.status == StepStatus.COMPLETED for step in run.steps)
    note_files = list((tmp_path / ".autodev" / "execution-notes").glob("coding-*.md"))
    assert note_files


def test_approval_mode_deny_fails_only_that_task_and_execution_continues(tmp_path: Path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    session_id = _start_session(orchestrator)
    run = orchestrator.execute_plan(session_id, mode=ExecutionMode.APPROVAL)
    pending = orchestrator.list_pending_execution_decisions(tenant_id=DEFAULT_TENANT_ID)
    denied_task_id = pending[0].task_id

    orchestrator.resolve_execution_decision(
        pending[0].decision_id, tenant_id=DEFAULT_TENANT_ID, decision="deny", actor="tester"
    )
    resumed = orchestrator.resume_plan_execution(session_id, run.run_id, mode=ExecutionMode.APPROVAL)

    denied_step = next(step for step in resumed.steps if step.step_key == denied_task_id)
    assert denied_step.status == StepStatus.FAILED
    assert len(resumed.steps) > len(run.steps)


def test_hybrid_mode_pauses_only_on_categories_not_covered_by_policy(tmp_path: Path) -> None:
    policy_store = PolicyStore(db_path=tmp_path / "policy.db")
    policy_service = PolicyService(store=policy_store)
    policy_service.set_rule(
        DEFAULT_TENANT_ID,
        PolicyRule(
            category=PolicyCategory.VALIDATION,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
        ),
    )
    decision_service = DecisionService(store=policy_store)
    orchestrator = _build_orchestrator(tmp_path, policy_service=policy_service, decision_service=decision_service)
    session_id = _start_session(orchestrator)

    run = orchestrator.execute_plan(session_id, mode=ExecutionMode.HYBRID)

    assert run.status == RunStatus.AWAITING_APPROVAL
    paused_steps = [step for step in run.steps if step.status == StepStatus.AWAITING_APPROVAL]
    assert len(paused_steps) == 1
    assert paused_steps[0].step_key.startswith("coding-")


def test_hybrid_always_grant_prevents_a_repeat_pause_for_the_same_command(tmp_path: Path) -> None:
    policy_store = PolicyStore(db_path=tmp_path / "policy.db")
    policy_service = PolicyService(store=policy_store)
    decision_service = DecisionService(store=policy_store)
    orchestrator = _build_orchestrator(tmp_path, policy_service=policy_service, decision_service=decision_service)
    # A stored rule for an unrelated category disables the local-mode
    # permissive fallback for every category, so "validation" (below) is
    # genuinely uncovered until the "always" grant covers it.
    policy_service.set_rule(
        DEFAULT_TENANT_ID,
        PolicyRule(
            category=PolicyCategory.PATCH,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
        ),
    )

    task_a = ExecutionTask(
        task_id="validation-a", title="Run ruff", description="Run ruff over backend",
        source_agent="validator", category="validation",
    )
    task_b = ExecutionTask(
        task_id="validation-b", title="Run ruff again", description="Run ruff over frontend",
        source_agent="validator", category="validation",
    )

    outcome_a, pending_a = orchestrator._resolve_task_actions(
        task=task_a,
        actions=orchestrator._task_executor.derive_actions(task_a),
        run_id="run-1",
        tenant_id=DEFAULT_TENANT_ID,
        mode=ExecutionMode.HYBRID,
    )
    assert outcome_a is None
    assert pending_a is not None
    assert pending_a.status == DecisionStatus.PENDING

    orchestrator.resolve_execution_decision(
        pending_a.decision_id,
        tenant_id=DEFAULT_TENANT_ID,
        decision="approve",
        actor="tester",
        persist_as_rule=True,
    )

    outcome_b, pending_b = orchestrator._resolve_task_actions(
        task=task_b,
        actions=orchestrator._task_executor.derive_actions(task_b),
        run_id="run-1",
        tenant_id=DEFAULT_TENANT_ID,
        mode=ExecutionMode.HYBRID,
    )
    assert pending_b is None
    assert outcome_b is not None
    assert outcome_b.status == "completed"


def test_a_timed_out_decision_denies_and_does_not_repause(tmp_path: Path) -> None:
    clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    policy_store = PolicyStore(db_path=tmp_path / "policy.db")
    policy_service = PolicyService(store=policy_store)
    decision_service = DecisionService(store=policy_store, now=lambda: clock["now"])
    orchestrator = _build_orchestrator(tmp_path, policy_service=policy_service, decision_service=decision_service)
    session_id = _start_session(orchestrator)

    run = orchestrator.execute_plan(session_id, mode=ExecutionMode.APPROVAL)
    assert run.status == RunStatus.AWAITING_APPROVAL
    paused_task_id = next(step.step_key for step in run.steps if step.status == StepStatus.AWAITING_APPROVAL)

    clock["now"] = clock["now"] + timedelta(hours=2)
    resumed = orchestrator.resume_plan_execution(session_id, run.run_id, mode=ExecutionMode.APPROVAL)

    resolved_step = next(step for step in resumed.steps if step.step_key == paused_task_id)
    assert resolved_step.status == StepStatus.FAILED


def test_resume_raises_when_the_run_is_not_awaiting_a_decision(tmp_path: Path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    session_id = _start_session(orchestrator)
    run = orchestrator.execute_plan(session_id, mode=ExecutionMode.AUTO)
    assert run.status == RunStatus.COMPLETED

    try:
        orchestrator.resume_plan_execution(session_id, run.run_id)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
