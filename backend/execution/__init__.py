"""Real task execution (E14-S1, RFC-009/ADR-021).

Turns an ``ExecutionTask`` into real, auditable work — replacing the
simulated loop that used to live in
``OrchestratorService._execute_plan_run``. See
:mod:`backend.execution.contracts` for the action/result contract,
:mod:`backend.execution.runner` for the S1 in-process runner, and
:mod:`backend.execution.executor` for the task-to-action mapping.
"""

from __future__ import annotations

from backend.execution.contracts import ExecutionAction, ExecutionActionType, ExecutionResult
from backend.execution.executor import TaskExecutionOutcome, TaskExecutor
from backend.execution.runner import ActionRunner, InProcessActionRunner

__all__ = [
    "ExecutionAction",
    "ExecutionActionType",
    "ExecutionResult",
    "TaskExecutionOutcome",
    "TaskExecutor",
    "ActionRunner",
    "InProcessActionRunner",
]
