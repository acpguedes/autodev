"""Tests for :class:`TaskExecutor` (E14-S1, RFC-009).

Uses a fake :class:`~backend.execution.runner.ActionRunner` so the mapping
and eventing behavior can be verified without touching the filesystem or a
real sandbox.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from backend.events.runtime import get_event_bus, reset_event_bus_for_tests
from backend.execution.contracts import ExecutionAction, ExecutionResult
from backend.execution.executor import TaskExecutor
from backend.execution.policy import PolicyDecision
from backend.orchestrator.service import ExecutionTask


@pytest.fixture(autouse=True)
def _reset_bus() -> Iterator[None]:
    reset_event_bus_for_tests()
    yield
    reset_event_bus_for_tests()


@dataclass
class _FakeRunner:
    """Records dispatched actions and returns a scripted result per action id."""

    outcomes: dict[str, str]
    dispatched: list[ExecutionAction]

    def run(self, action: ExecutionAction) -> ExecutionResult:
        self.dispatched.append(action)
        now = datetime.now(timezone.utc).isoformat()
        status = self.outcomes.get(action.action_id, "succeeded")
        return ExecutionResult(
            action_id=action.action_id,
            task_id=action.task_id,
            step_key=action.step_key,
            status=status,
            started_at=now,
            completed_at=now,
            error="boom" if status == "failed" else None,
        )


def _task(task_id: str, category: str, description: str) -> ExecutionTask:
    return ExecutionTask(
        task_id=task_id,
        title=f"Title for {task_id}",
        description=description,
        source_agent="coder",
        category=category,
    )


def test_validation_task_with_a_known_tool_dispatches_one_run_validation_action() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("validation-1", "validation", "Run pytest for backend modules")

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert len(runner.dispatched) == 1
    assert runner.dispatched[0].type.value == "run_validation"
    assert runner.dispatched[0].command == ["pytest"]


def test_validation_task_with_no_known_tool_dispatches_nothing() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("validation-2", "validation", "Review the checklist manually")

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert runner.dispatched == []
    assert outcome.results == []


def test_implementation_task_dispatches_one_create_file_action_under_execution_notes() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("coding-1", "implementation", "Add the missing endpoint")

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert len(runner.dispatched) == 1
    action = runner.dispatched[0]
    assert action.type.value == "create_file"
    assert action.path == ".autodev/execution-notes/coding-1.md"
    assert "Add the missing endpoint" in (action.content or "")


def test_implementation_task_with_files_dispatches_one_create_file_action_per_file() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = ExecutionTask(
        task_id="coding-file-1",
        title="Write backend/payments/charge.py",
        description="Write real file content to backend/payments/charge.py",
        source_agent="coder",
        category="implementation",
        files=[
            {"path": "backend/payments/charge.py", "content": "def charge(): ...\n"},
            {"path": "backend/payments/__init__.py", "content": ""},
        ],
    )

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert len(runner.dispatched) == 2
    assert runner.dispatched[0].type.value == "create_file"
    assert runner.dispatched[0].path == "backend/payments/charge.py"
    assert runner.dispatched[0].content == "def charge(): ...\n"
    assert runner.dispatched[1].path == "backend/payments/__init__.py"


@pytest.mark.parametrize("category", ["planning", "analysis", "architecture", "operations"])
def test_categories_without_a_real_mapping_dispatch_nothing(category: str) -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("t-1", category, "Some free-text description")

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert runner.dispatched == []


def test_a_failed_action_marks_the_task_outcome_failed_and_emits_the_failed_event() -> None:
    runner = _FakeRunner(outcomes={"coding-1-note": "failed"}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("coding-1", "implementation", "Add the missing endpoint")

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "failed"
    assert outcome.results[0].status == "failed"

    envelopes = get_event_bus().replay("run-1")
    types = [envelope.type for envelope in envelopes]
    assert "execution.action.started" in types
    assert "execution.action.failed" in types
    assert "execution.action.completed" not in types


@dataclass
class _FakePolicy:
    """Always returns the scripted decision, recording each call."""

    decision: PolicyDecision
    calls: list[ExecutionAction]

    def evaluate(self, *, tenant_id: str, action: ExecutionAction, run_id: str, actor: str = "system"):
        self.calls.append(action)
        return self.decision


def test_a_policy_denied_action_never_reaches_the_runner() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    policy = _FakePolicy(decision=PolicyDecision(allowed=False, matched=True, reason="deny rule"), calls=[])
    executor = TaskExecutor(runner, policy=policy)
    task = _task("coding-1", "implementation", "Add the missing endpoint")

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "failed"
    assert outcome.results[0].status == "failed"
    assert "policy denied" in (outcome.results[0].error or "")
    assert runner.dispatched == []
    assert len(policy.calls) == 1

    envelopes = get_event_bus().replay("run-1")
    types = [envelope.type for envelope in envelopes]
    assert types == ["execution.action.failed"]


def test_a_policy_allowed_action_reaches_the_runner_as_before() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    policy = _FakePolicy(decision=PolicyDecision(allowed=True, matched=True, reason="allow rule"), calls=[])
    executor = TaskExecutor(runner, policy=policy)
    task = _task("coding-1", "implementation", "Add the missing endpoint")

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert len(runner.dispatched) == 1
    assert len(policy.calls) == 1


def test_a_succeeded_action_emits_started_and_completed_events() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("validation-1", "validation", "Run pytest for backend modules")

    executor.execute(task, run_id="run-2", tenant_id="acme")

    envelopes = get_event_bus().replay("run-2")
    types = [envelope.type for envelope in envelopes]
    assert types == ["execution.action.started", "execution.action.completed"]
