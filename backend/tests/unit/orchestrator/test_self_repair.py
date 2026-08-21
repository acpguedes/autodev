"""Tests for E41-S5: self-verification loop (generate -> test -> repair).

Drives ``OrchestratorService._maybe_self_repair`` directly rather than a
full end-to-end run through the real command sandbox: sandbox execution is
Docker/flag-dependent (AUTODEV_ENABLE_SANDBOX, Docker on PATH), which would
make the revalidation outcome environment-dependent rather than a
deterministic unit test. The write half of the repair (patch-engine apply)
is exercised for real; only the revalidation dispatch is scripted via a
thin proxy over the real TaskExecutor, so real file content still lands on
disk under a real project root.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.agents.base import AgentContext, AgentResult
from backend.events.runtime import get_event_bus, reset_event_bus_for_tests
from backend.execution.contracts import ExecutionFailureKind, ExecutionResult
from backend.execution.executor import TaskExecutionOutcome
from backend.execution.modes import ExecutionMode
from backend.orchestrator.service import ExecutionTask, OrchestratorService
from backend.persistence import DurableStore


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_event_bus_for_tests()
    yield
    reset_event_bus_for_tests()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_orchestrator(tmp_path: Path) -> OrchestratorService:
    store = DurableStore(f"sqlite:///{tmp_path / 'autodev-test.db'}")
    return OrchestratorService(store=store, project_root=tmp_path)


class _FakeRepairCoderAgent:
    """Returns scripted repaired file content and counts invocations."""

    name = "coder"

    def __init__(self, files: list[dict[str, str]]) -> None:
        self._files = files
        self.call_count = 0

    def run(self, context: AgentContext) -> AgentResult:
        self.call_count += 1
        return AgentResult(
            content="Repaired the failing file.",
            metadata={"coding_tasks": [], "files": self._files, "test_updates": [], "touched_components": []},
        )


class _ScriptedRevalidationExecutor:
    """Delegates to the real TaskExecutor, except it scripts run_validation dispatches."""

    def __init__(self, real_executor, *, revalidation_succeeds: bool) -> None:
        self._real = real_executor
        self._revalidation_succeeds = revalidation_succeeds

    def derive_actions(self, task):
        return self._real.derive_actions(task)

    def dispatch(self, actions, *, run_id, tenant_id, actor="system", pre_approved_action_ids=frozenset()):
        if actions and all(action.type.value == "run_validation" for action in actions):
            now = _timestamp()
            status = "succeeded" if self._revalidation_succeeds else "failed"
            results = [
                ExecutionResult(
                    action_id=action.action_id,
                    task_id=action.task_id,
                    step_key=action.step_key,
                    status=status,
                    started_at=now,
                    completed_at=now,
                    stdout="tests passed" if self._revalidation_succeeds else "",
                    stderr="" if self._revalidation_succeeds else "AssertionError: still broken",
                    error=None if self._revalidation_succeeds else "AssertionError: still broken",
                )
                for action in actions
            ]
            outcome_status = "completed" if self._revalidation_succeeds else "failed"
            return TaskExecutionOutcome(status=outcome_status, results=results)
        return self._real.dispatch(
            actions,
            run_id=run_id,
            tenant_id=tenant_id,
            actor=actor,
            pre_approved_action_ids=pre_approved_action_ids,
        )

    def deny_all(self, actions, *, run_id, tenant_id, reason):
        return self._real.deny_all(actions, run_id=run_id, tenant_id=tenant_id, reason=reason)


def _validation_task() -> ExecutionTask:
    return ExecutionTask(
        task_id="validation-command-1",
        title="Run pytest tests/test_charge.py",
        description="Run agent-declared command: pytest tests/test_charge.py",
        source_agent="validator",
        category="validation",
        commands=["pytest tests/test_charge.py"],
    )


def _first_attempt_outcome(task: ExecutionTask) -> TaskExecutionOutcome:
    now = _timestamp()
    return TaskExecutionOutcome(
        status="failed",
        results=[
            ExecutionResult(
                action_id=f"{task.task_id}-validate-1",
                task_id=task.task_id,
                step_key=task.task_id,
                status="failed",
                started_at=now,
                completed_at=now,
                stderr="AssertionError: charge() returned False",
                error="AssertionError: charge() returned False",
            )
        ],
    )


def _prior_write_result(path: str) -> ExecutionResult:
    now = _timestamp()
    return ExecutionResult(
        action_id="coding-file-1-write-1",
        task_id="coding-file-1",
        step_key="coding-file-1",
        status="succeeded",
        started_at=now,
        completed_at=now,
        artifacts=[path],
    )


def test_self_repair_repairs_and_revalidation_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    target_path = "backend/payments/charge.py"
    broken_content = "def charge():\n    return False\n"
    repaired_content = "def charge():\n    return True\n"
    (tmp_path / target_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / target_path).write_text(broken_content)

    orchestrator = _build_orchestrator(tmp_path)
    coder = _FakeRepairCoderAgent(files=[{"path": target_path, "content": repaired_content}])
    orchestrator._agents["coder"] = coder
    orchestrator._task_executor = _ScriptedRevalidationExecutor(  # type: ignore[assignment]
        orchestrator._task_executor, revalidation_succeeds=True
    )

    task = _validation_task()
    outcome, self_check = orchestrator._maybe_self_repair(
        task=task,
        validation_outcome=_first_attempt_outcome(task),
        batch_results=[_prior_write_result(target_path)],
        run_id="run-1",
        tenant_id="acme",
        mode=ExecutionMode.AUTO,
    )

    assert self_check == "repaired_then_pass"
    assert outcome.status == "completed"
    assert coder.call_count == 1
    assert (tmp_path / target_path).read_text() == repaired_content


def test_self_repair_reports_failed_after_retry_when_revalidation_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    target_path = "backend/payments/charge.py"
    (tmp_path / target_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / target_path).write_text("def charge():\n    return False\n")

    orchestrator = _build_orchestrator(tmp_path)
    coder = _FakeRepairCoderAgent(
        files=[{"path": target_path, "content": "def charge():\n    return False  # still broken\n"}]
    )
    orchestrator._agents["coder"] = coder
    orchestrator._task_executor = _ScriptedRevalidationExecutor(  # type: ignore[assignment]
        orchestrator._task_executor, revalidation_succeeds=False
    )

    task = _validation_task()
    outcome, self_check = orchestrator._maybe_self_repair(
        task=task,
        validation_outcome=_first_attempt_outcome(task),
        batch_results=[_prior_write_result(target_path)],
        run_id="run-1",
        tenant_id="acme",
        mode=ExecutionMode.AUTO,
    )

    assert self_check == "failed_after_retry"
    assert outcome.status == "failed"
    assert coder.call_count == 1, "no unbounded retry — exactly one repair attempt"


def test_self_repair_first_try_pass_short_circuits_without_calling_coder(tmp_path: Path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    coder = _FakeRepairCoderAgent(files=[])
    orchestrator._agents["coder"] = coder
    task = _validation_task()
    passing_outcome = TaskExecutionOutcome(status="completed", results=[])

    outcome, self_check = orchestrator._maybe_self_repair(
        task=task,
        validation_outcome=passing_outcome,
        batch_results=[],
        run_id="run-1",
        tenant_id="acme",
        mode=ExecutionMode.AUTO,
    )

    assert self_check == "first_try_pass"
    assert outcome is passing_outcome
    assert coder.call_count == 0


def test_self_repair_with_no_prior_file_artifacts_is_reported_failed_without_retry(
    tmp_path: Path,
) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    coder = _FakeRepairCoderAgent(files=[])
    orchestrator._agents["coder"] = coder
    task = _validation_task()

    outcome, self_check = orchestrator._maybe_self_repair(
        task=task,
        validation_outcome=_first_attempt_outcome(task),
        batch_results=[],
        run_id="run-1",
        tenant_id="acme",
        mode=ExecutionMode.AUTO,
    )

    assert self_check == "failed_after_retry"
    assert coder.call_count == 0


def _classified_failure_outcome(
    task: ExecutionTask, failure_kind: ExecutionFailureKind
) -> TaskExecutionOutcome:
    now = _timestamp()
    return TaskExecutionOutcome(
        status="failed",
        results=[
            ExecutionResult(
                action_id=f"{task.task_id}-validate-1",
                task_id=task.task_id,
                step_key=task.task_id,
                status="failed",
                started_at=now,
                completed_at=now,
                stderr="Command 'cd' is not in the allowed list.",
                error="Command 'cd' is not in the allowed list.",
                failure_kind=failure_kind,
            )
        ],
    )


def test_self_repair_skips_a_non_repairable_failure_without_calling_coder(tmp_path: Path) -> None:
    """E46-S2: a policy/environment failure never reaches the Coder."""
    orchestrator = _build_orchestrator(tmp_path)
    coder = _FakeRepairCoderAgent(files=[])
    orchestrator._agents["coder"] = coder
    task = _validation_task()

    outcome, self_check = orchestrator._maybe_self_repair(
        task=task,
        validation_outcome=_classified_failure_outcome(task, ExecutionFailureKind.COMMAND_NOT_ALLOWED),
        batch_results=[_prior_write_result("backend/payments/charge.py")],
        run_id="run-1",
        tenant_id="acme",
        mode=ExecutionMode.AUTO,
    )

    assert self_check == "skipped_non_repairable"
    assert outcome.status == "failed"
    assert coder.call_count == 0

    envelopes = get_event_bus().replay("run-1")
    skipped = [e for e in envelopes if e.type == "execution.repair.skipped"]
    assert len(skipped) == 1
    assert skipped[0].data["taskId"] == task.task_id
    assert skipped[0].data["failureKind"] == "command_not_allowed"


def test_self_repair_still_repairs_a_classified_code_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E46-S2: a genuine, classified code_failure still repairs exactly as E41-S5 defined."""
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    target_path = "backend/payments/charge.py"
    (tmp_path / target_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / target_path).write_text("def charge():\n    return False\n")

    orchestrator = _build_orchestrator(tmp_path)
    coder = _FakeRepairCoderAgent(files=[{"path": target_path, "content": "def charge():\n    return True\n"}])
    orchestrator._agents["coder"] = coder
    orchestrator._task_executor = _ScriptedRevalidationExecutor(  # type: ignore[assignment]
        orchestrator._task_executor, revalidation_succeeds=True
    )

    task = _validation_task()
    outcome, self_check = orchestrator._maybe_self_repair(
        task=task,
        validation_outcome=_classified_failure_outcome(task, ExecutionFailureKind.CODE_FAILURE),
        batch_results=[_prior_write_result(target_path)],
        run_id="run-1",
        tenant_id="acme",
        mode=ExecutionMode.AUTO,
    )

    assert self_check == "repaired_then_pass"
    assert coder.call_count == 1
    envelopes = get_event_bus().replay("run-1")
    assert not [e for e in envelopes if e.type == "execution.repair.skipped"]


def test_self_repair_fails_open_for_unclassified_legacy_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E46-S2-T3: a result with no failure_kind keeps today's reflex behavior."""
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    target_path = "backend/payments/charge.py"
    (tmp_path / target_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / target_path).write_text("def charge():\n    return False\n")

    orchestrator = _build_orchestrator(tmp_path)
    coder = _FakeRepairCoderAgent(
        files=[{"path": target_path, "content": "def charge():\n    return False  # still broken\n"}]
    )
    orchestrator._agents["coder"] = coder
    orchestrator._task_executor = _ScriptedRevalidationExecutor(  # type: ignore[assignment]
        orchestrator._task_executor, revalidation_succeeds=False
    )
    task = _validation_task()

    outcome, self_check = orchestrator._maybe_self_repair(
        task=task,
        validation_outcome=_first_attempt_outcome(task),  # failure_kind=None
        batch_results=[_prior_write_result(target_path)],
        run_id="run-1",
        tenant_id="acme",
        mode=ExecutionMode.AUTO,
    )

    assert self_check == "failed_after_retry"
    assert coder.call_count == 1, "unclassified results fail the gate open, not skip repair"


class _FailThenSucceedValidationExecutor:
    """Delegates to the real TaskExecutor, but fails the first run_validation
    dispatch and succeeds every one after — driving a real first-attempt
    failure through `_process_tasks` followed by a real repaired-pass
    revalidation, without depending on Docker/the real sandbox.
    """

    def __init__(self, real_executor) -> None:
        self._real = real_executor
        self._validation_calls = 0

    def derive_actions(self, task):
        return self._real.derive_actions(task)

    def dispatch(self, actions, *, run_id, tenant_id, actor="system", pre_approved_action_ids=frozenset()):
        if actions and all(action.type.value == "run_validation" for action in actions):
            self._validation_calls += 1
            succeeds = self._validation_calls > 1
            now = _timestamp()
            status = "succeeded" if succeeds else "failed"
            results = [
                ExecutionResult(
                    action_id=action.action_id,
                    task_id=action.task_id,
                    step_key=action.step_key,
                    status=status,
                    started_at=now,
                    completed_at=now,
                    stdout="tests passed" if succeeds else "",
                    stderr="" if succeeds else "AssertionError: still broken",
                    error=None if succeeds else "AssertionError: still broken",
                )
                for action in actions
            ]
            return TaskExecutionOutcome(
                status="completed" if succeeds else "failed", results=results
            )
        return self._real.dispatch(
            actions,
            run_id=run_id,
            tenant_id=tenant_id,
            actor=actor,
            pre_approved_action_ids=pre_approved_action_ids,
        )

    def deny_all(self, actions, *, run_id, tenant_id, reason):
        return self._real.deny_all(actions, run_id=run_id, tenant_id=tenant_id, reason=reason)

    def execute(self, task, *, run_id, tenant_id, actor="system"):
        return self.dispatch(
            self.derive_actions(task), run_id=run_id, tenant_id=tenant_id, actor=actor
        )


class _FakeValidatorAgent:
    """Stands in for ValidatorAgent, returning a structured command (E41-S4 shape)."""

    name = "validator"

    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult(
            content="Validation steps:\n- Verify the charge endpoint behaves correctly",
            metadata={
                "validation_steps": [],
                "success_criteria": [],
                "commands": ["pytest tests/test_charge.py"],
            },
        )


def test_execute_plan_end_to_end_repairs_a_failing_task_and_surfaces_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E41-S5: a full execute_plan run repairs a first-attempt failure and reports it."""
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    target_path = "backend/payments/charge.py"
    repaired_content = "def charge():\n    return True\n"

    orchestrator = _build_orchestrator(tmp_path)
    orchestrator._agents["coder"] = _FakeRepairCoderAgent(
        files=[{"path": target_path, "content": repaired_content}]
    )
    orchestrator._agents["validator"] = _FakeValidatorAgent()
    orchestrator._task_executor = _FailThenSucceedValidationExecutor(  # type: ignore[assignment]
        orchestrator._task_executor
    )

    session = orchestrator.create_plan("Criar plano executável por tarefas")
    orchestrator.handle_message(
        session.session_id, "produza análise e checklist de implementação"
    )

    run = orchestrator.execute_plan(session.session_id, mode=ExecutionMode.AUTO)

    validation_results = [
        result for result in run.results if "self_check" in result.metadata
    ]
    assert validation_results, "expected a self-checked validation task in the run results"
    assert validation_results[0].metadata["self_check"] == "repaired_then_pass"
    assert validation_results[0].metadata["status"] == "completed"
    assert (tmp_path / target_path).read_text() == repaired_content

    envelopes = get_event_bus().replay(run.run_id)
    outcome_events = [e for e in envelopes if e.type == "execution.verification.outcome"]
    assert outcome_events
    assert outcome_events[0].data["outcome"] == "repaired_then_pass"
