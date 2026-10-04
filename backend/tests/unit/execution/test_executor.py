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
from backend.execution.contracts import ExecutionAction, ExecutionFailureKind, ExecutionResult
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
            stdout="scripted stdout" if status != "failed" else "",
            stderr="scripted stderr" if status == "failed" else "",
            command=list(action.command) if action.command else None,
            path=action.path,
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


def test_implementation_task_step_label_is_a_plain_language_creating_line() -> None:
    """E43-S3: a file-write action is labeled "Creating <file>", not the raw task id."""
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = ExecutionTask(
        task_id="coding-file-1",
        title="Write backend/payments/charge.py",
        description="Write real file content to backend/payments/charge.py",
        source_agent="coder",
        category="implementation",
        files=[{"path": "backend/payments/charge.py", "content": "def charge(): ...\n"}],
    )

    executor.execute(task, run_id="run-5", tenant_id="acme")

    assert runner.dispatched[0].step_label == "Creating charge.py"

    envelopes = get_event_bus().replay("run-5")
    started = next(e for e in envelopes if e.type == "execution.action.started")
    assert started.data["stepLabel"] == "Creating charge.py"


def test_validation_task_step_label_is_the_task_title() -> None:
    """E43-S3: a validation/operations action falls back to the task's own title."""
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("validation-1", "validation", "Run pytest for backend modules")

    executor.execute(task, run_id="run-6", tenant_id="acme")

    assert runner.dispatched[0].step_label == "Title for validation-1"


def test_validation_task_with_structured_commands_ignores_keyword_sniffing() -> None:
    """E41-S4: a command absent from free text but present in `commands` still runs."""
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = ExecutionTask(
        task_id="validation-command-1",
        title="Run pip install -e .",
        description="Run agent-declared command: pip install -e .",
        source_agent="validator",
        category="validation",
        commands=["pip install -e ."],
    )

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert len(runner.dispatched) == 1
    assert runner.dispatched[0].type.value == "run_validation"
    assert runner.dispatched[0].command == ["pip", "install", "-e", "."]


def test_validation_task_without_structured_commands_still_uses_keyword_sniffing() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("validation-1", "validation", "Run pytest for backend modules")

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert len(runner.dispatched) == 1
    assert runner.dispatched[0].command == ["pytest"]


def test_operations_task_with_structured_commands_dispatches_run_command() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = ExecutionTask(
        task_id="devops-command-1",
        title="Run pip install -e .",
        description="Run agent-declared command: pip install -e .",
        source_agent="devops",
        category="operations",
        commands=["pip install -e ."],
    )

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert len(runner.dispatched) == 1
    assert runner.dispatched[0].type.value == "run_command"
    assert runner.dispatched[0].command == ["pip", "install", "-e", "."]


def test_operations_task_without_structured_commands_dispatches_nothing() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("devops-1", "operations", "Keep the service runnable")

    outcome = executor.execute(task, run_id="run-1", tenant_id="acme")

    assert outcome.status == "completed"
    assert runner.dispatched == []


@pytest.mark.parametrize("category", ["planning", "analysis", "architecture"])
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
    assert outcome.results[0].failure_kind is ExecutionFailureKind.POLICY_DENIED
    assert outcome.results[0].repairable_by_code_change is False
    assert runner.dispatched == []
    assert len(policy.calls) == 1

    envelopes = get_event_bus().replay("run-1")
    types = [envelope.type for envelope in envelopes]
    assert types == ["execution.action.failed"]
    assert envelopes[0].data["failureKind"] == "policy_denied"


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


def test_completed_and_failed_events_carry_the_real_command_and_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """E43-S2: a transcript renderer needs the real command/output on the
    wire, not just the action id and exit code."""
    executor = TaskExecutor(_FakeRunner(outcomes={}, dispatched=[]))
    task = _task("validation-1", "validation", "Run pytest for backend modules")

    executor.execute(task, run_id="run-3", tenant_id="acme")

    envelopes = get_event_bus().replay("run-3")
    completed = next(e for e in envelopes if e.type == "execution.action.completed")
    assert completed.data["command"] == ["pytest"]
    assert completed.data["stdout"] == "scripted stdout"

    failing_executor = TaskExecutor(_FakeRunner(outcomes={"validation-2-validate": "failed"}, dispatched=[]))
    failing_task = _task("validation-2", "validation", "Run pytest for backend modules")

    failing_executor.execute(failing_task, run_id="run-4", tenant_id="acme")

    envelopes = get_event_bus().replay("run-4")
    failed = next(e for e in envelopes if e.type == "execution.action.failed")
    assert failed.data["command"] == ["pytest"]
    assert failed.data["stderr"] == "scripted stderr"


def test_deny_all_defaults_to_policy_denied_failure_kind() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("coding-1", "implementation", "Add the missing endpoint")
    actions = executor.derive_actions(task)

    outcome = executor.deny_all(actions, run_id="run-1", tenant_id="acme", reason="human denied this action")

    assert outcome.results[0].failure_kind is ExecutionFailureKind.POLICY_DENIED
    envelopes = get_event_bus().replay("run-1")
    assert envelopes[0].data["failureKind"] == "policy_denied"


def test_deny_all_accepts_an_explicit_failure_kind() -> None:
    runner = _FakeRunner(outcomes={}, dispatched=[])
    executor = TaskExecutor(runner)
    task = _task("coding-1", "implementation", "Add the missing endpoint")
    actions = executor.derive_actions(task)

    outcome = executor.deny_all(
        actions,
        run_id="run-1",
        tenant_id="acme",
        reason="execution environment unavailable: boom",
        failure_kind=ExecutionFailureKind.ENVIRONMENT_UNAVAILABLE,
    )

    assert outcome.results[0].failure_kind is ExecutionFailureKind.ENVIRONMENT_UNAVAILABLE


def test_events_carry_source_agent_and_failed_carries_exit_code_and_truncation() -> None:
    """E64-S2: started/completed/failed name the originating agent; truncation is explicit."""
    executor = TaskExecutor(_FakeRunner(outcomes={}, dispatched=[]))
    executor.execute(_task("validation-1", "validation", "Run pytest"), run_id="run-s2", tenant_id="acme")
    envelopes = get_event_bus().replay("run-s2")
    assert {e.data["sourceAgent"] for e in envelopes} == {"coder"}
    completed = next(e for e in envelopes if e.type == "execution.action.completed")
    assert completed.data["truncated"] is False

    failing = TaskExecutor(_FakeRunner(outcomes={"validation-2-validate": "failed"}, dispatched=[]))
    failing.execute(_task("validation-2", "validation", "Run pytest"), run_id="run-s2b", tenant_id="acme")
    failed = next(e for e in get_event_bus().replay("run-s2b") if e.type == "execution.action.failed")
    assert failed.data["sourceAgent"] == "coder"
    assert failed.data["truncated"] is False


def test_oversized_output_is_flagged_truncated() -> None:
    @dataclass
    class _Big(_FakeRunner):
        def run(self, action: ExecutionAction) -> ExecutionResult:
            result = super().run(action)
            result.stdout = "x" * 5000
            return result

    TaskExecutor(_Big(outcomes={}, dispatched=[])).execute(
        _task("validation-1", "validation", "Run pytest"), run_id="run-trunc", tenant_id="acme"
    )
    completed = next(e for e in get_event_bus().replay("run-trunc") if e.type == "execution.action.completed")
    assert completed.data["truncated"] is True
    assert len(completed.data["stdout"]) == 4000


@dataclass
class _StreamingRunner(_FakeRunner):
    """Feeds scripted ``(stream, text)`` pieces to ``on_chunk`` like the sandbox does."""

    pieces: tuple[tuple[str, str], ...] = ()

    def run(self, action: ExecutionAction, on_chunk=None) -> ExecutionResult:  # type: ignore[no-untyped-def]
        for stream, text in self.pieces:
            on_chunk(stream, text)
        return super().run(action)


def _output_chunks(run_id: str) -> list[dict]:  # type: ignore[type-arg]
    return [e.data for e in get_event_bus().replay(run_id) if e.type == "execution.action.output"]


def test_output_is_emitted_on_line_boundaries_in_order() -> None:
    runner = _StreamingRunner(
        outcomes={}, dispatched=[], pieces=(("stdout", "one\ntw"), ("stdout", "o\n"), ("stderr", "err"))
    )
    TaskExecutor(runner).execute(
        _task("validation-1", "validation", "Run pytest"), run_id="run-chunks", tenant_id="acme"
    )
    chunks = _output_chunks("run-chunks")
    assert [(c["stream"], c["chunk"]) for c in chunks] == [
        ("stdout", "one\n"),
        ("stdout", "two\n"),
        ("stderr", "err"),
    ]
    assert [c["seq"] for c in chunks] == [1, 2, 3]
    assert all(c["actionId"] == "validation-1-validate" for c in chunks)


def test_a_secret_split_across_chunks_is_redacted_in_output_events() -> None:
    """E64-S3-T3: a live secret split mid-token across two reads never escapes."""
    from backend.secret_store.redaction import (
        REDACTED_MARKER,
        register_live_secret_value,
        reset_registry_for_tests,
    )

    reset_registry_for_tests()
    register_live_secret_value("sk-live-ABCDEF123456")
    try:
        runner = _StreamingRunner(
            outcomes={}, dispatched=[], pieces=(("stdout", "token=sk-live-ABC"), ("stdout", "DEF123456 done\n"))
        )
        TaskExecutor(runner).execute(
            _task("validation-1", "validation", "Run pytest"), run_id="run-secret", tenant_id="acme"
        )
    finally:
        reset_registry_for_tests()
    text = "".join(c["chunk"] for c in _output_chunks("run-secret"))
    assert "sk-live" not in text and "ABC" not in text
    assert text == f"token={REDACTED_MARKER} done\n"


def test_runner_without_on_chunk_still_works_and_emits_no_output_events() -> None:
    TaskExecutor(_FakeRunner(outcomes={}, dispatched=[])).execute(
        _task("validation-1", "validation", "Run pytest"), run_id="run-plain", tenant_id="acme"
    )
    assert _output_chunks("run-plain") == []
