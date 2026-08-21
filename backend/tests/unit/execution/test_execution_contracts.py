"""Tests for the execution action/result contract (E14-S1, RFC-009)."""

from __future__ import annotations

from backend.execution.contracts import ExecutionActionType, ExecutionFailureKind, ExecutionResult


def test_execution_result_to_dict_round_trips_all_fields() -> None:
    result = ExecutionResult(
        action_id="task-1-note",
        task_id="task-1",
        step_key="task-1",
        status="succeeded",
        started_at="2026-08-17T00:00:00+00:00",
        completed_at="2026-08-17T00:00:01+00:00",
        stdout="ok",
        stderr="",
        exit_code=0,
        diff="--- a\n+++ b\n",
        artifacts=["notes/task-1.md"],
        error=None,
        command=["pytest", "-q"],
        path="notes/task-1.md",
    )

    payload = result.to_dict()

    assert payload == {
        "action_id": "task-1-note",
        "task_id": "task-1",
        "step_key": "task-1",
        "status": "succeeded",
        "started_at": "2026-08-17T00:00:00+00:00",
        "completed_at": "2026-08-17T00:00:01+00:00",
        "stdout": "ok",
        "stderr": "",
        "exit_code": 0,
        "diff": "--- a\n+++ b\n",
        "artifacts": ["notes/task-1.md"],
        "error": None,
        "environment": {},
        "command": ["pytest", "-q"],
        "path": "notes/task-1.md",
        "failure_kind": None,
    }


def test_execution_action_type_values_match_the_five_documented_kinds() -> None:
    assert {member.value for member in ExecutionActionType} == {
        "create_file",
        "edit_file",
        "apply_patch",
        "run_command",
        "run_validation",
    }


def test_execution_failure_kind_values_match_the_seven_documented_kinds() -> None:
    assert {member.value for member in ExecutionFailureKind} == {
        "code_failure",
        "command_not_allowed",
        "policy_denied",
        "environment_unavailable",
        "dependency_missing",
        "timeout",
        "internal_error",
    }


def _failed_result(failure_kind: ExecutionFailureKind | None) -> ExecutionResult:
    return ExecutionResult(
        action_id="a1",
        task_id="task-1",
        step_key="task-1",
        status="failed",
        started_at="2026-08-21T00:00:00+00:00",
        completed_at="2026-08-21T00:00:01+00:00",
        failure_kind=failure_kind,
    )


def test_repairable_by_code_change_true_only_for_code_failure() -> None:
    assert _failed_result(ExecutionFailureKind.CODE_FAILURE).repairable_by_code_change is True
    for kind in ExecutionFailureKind:
        if kind is ExecutionFailureKind.CODE_FAILURE:
            continue
        assert _failed_result(kind).repairable_by_code_change is False
    assert _failed_result(None).repairable_by_code_change is False


def test_failure_kind_serializes_to_its_string_value_in_to_dict() -> None:
    payload = _failed_result(ExecutionFailureKind.COMMAND_NOT_ALLOWED).to_dict()

    assert payload["failure_kind"] == "command_not_allowed"
