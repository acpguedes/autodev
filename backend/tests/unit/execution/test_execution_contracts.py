"""Tests for the execution action/result contract (E14-S1, RFC-009)."""

from __future__ import annotations

from backend.execution.contracts import ExecutionActionType, ExecutionResult


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
    }


def test_execution_action_type_values_match_the_five_documented_kinds() -> None:
    assert {member.value for member in ExecutionActionType} == {
        "create_file",
        "edit_file",
        "apply_patch",
        "run_command",
        "run_validation",
    }
