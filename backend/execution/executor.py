"""Maps an ``ExecutionTask`` to real :class:`ExecutionAction`s and runs them.

Replaces the simulated loop that used to live in
``OrchestratorService._execute_plan_run``: each task is translated into zero
or more actions via a deliberately simple, category-based heuristic (S1
scope — the current planner/coder/validator agents produce free-text task
descriptions, not structured file/command data; a smarter mapping driven by
real code generation is future work), dispatched to an injected
:class:`~backend.execution.runner.ActionRunner`, and reported via
``execution.action.*`` events (RFC-009).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from backend.events.runtime import emit_event
from backend.execution.contracts import ExecutionAction, ExecutionActionType, ExecutionResult
from backend.execution.policy import PolicyEvaluator
from backend.execution.runner import ActionRunner

if TYPE_CHECKING:
    from backend.orchestrator.service import ExecutionTask


def _timestamp() -> str:
    """Return the current UTC time in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()

_VALIDATION_COMMANDS = ("pytest", "ruff", "npm", "python3", "python")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")


def _extract_validation_command(description: str) -> list[str] | None:
    """Find the first known validation tool named in *description*, if any."""
    for token in _TOKEN_RE.findall(description.lower()):
        if token in _VALIDATION_COMMANDS:
            return [token]
    return None


@dataclass(slots=True)
class TaskExecutionOutcome:
    """Aggregate outcome of executing one task's derived actions.

    Attributes:
        status: ``"completed"`` if every derived action succeeded (or none
            were derived), ``"failed"`` if at least one action failed.
        results: The per-action results, in dispatch order.
    """

    status: str
    results: list[ExecutionResult]


class TaskExecutor:
    """Turns ``ExecutionTask``s into real work via an injected runner."""

    def __init__(self, runner: ActionRunner, policy: Optional[PolicyEvaluator] = None) -> None:
        """Initialize the executor.

        Args:
            runner: Where derived actions are dispatched to run.
            policy: Optional policy gate (E14-S2, RFC-010) consulted before
                every dispatch; ``None`` preserves E14-S1's unguarded
                behavior (used for direct/test construction —
                :class:`~backend.orchestrator.service.OrchestratorService`
                always wires a real
                :class:`~backend.execution.policy.PolicyService`).
        """
        self._runner = runner
        self._policy = policy

    def execute(
        self, task: "ExecutionTask", *, run_id: str, tenant_id: str, actor: str = "system"
    ) -> TaskExecutionOutcome:
        """Derive actions for *task*, run them, and report the aggregate outcome.

        Args:
            task: The plan task to turn into real work.
            run_id: Orchestrator run this execution belongs to (event partition key).
            tenant_id: Tenant the run belongs to.
            actor: Who/what is driving this execution (audited by policy
                evaluations; defaults to ``"system"`` for automatic runs).

        Returns:
            The aggregate outcome across every action derived from *task*.
        """
        actions = self._derive_actions(task)
        results: list[ExecutionResult] = []
        failed = False
        for action in actions:
            if self._policy is not None:
                decision = self._policy.evaluate(
                    tenant_id=tenant_id, action=action, run_id=run_id, actor=actor
                )
                if not decision.allowed:
                    failed = True
                    now = _timestamp()
                    result = ExecutionResult(
                        action_id=action.action_id,
                        task_id=action.task_id,
                        step_key=action.step_key,
                        status="failed",
                        started_at=now,
                        completed_at=now,
                        error=f"policy denied: {decision.reason}",
                    )
                    results.append(result)
                    emit_event(
                        "execution.action.failed",
                        tenant_id=tenant_id,
                        partition_key=run_id,
                        data={
                            "actionId": action.action_id,
                            "taskId": action.task_id,
                            "error": result.error or "",
                        },
                        subject={"runId": run_id, "taskId": action.task_id},
                    )
                    continue
            emit_event(
                "execution.action.started",
                tenant_id=tenant_id,
                partition_key=run_id,
                data={"actionId": action.action_id, "taskId": action.task_id, "type": action.type.value},
                subject={"runId": run_id, "taskId": action.task_id},
            )
            result = self._runner.run(action)
            results.append(result)
            if result.status == "failed":
                failed = True
                emit_event(
                    "execution.action.failed",
                    tenant_id=tenant_id,
                    partition_key=run_id,
                    data={
                        "actionId": action.action_id,
                        "taskId": action.task_id,
                        "error": result.error or "",
                    },
                    subject={"runId": run_id, "taskId": action.task_id},
                )
            else:
                emit_event(
                    "execution.action.completed",
                    tenant_id=tenant_id,
                    partition_key=run_id,
                    data={
                        "actionId": action.action_id,
                        "taskId": action.task_id,
                        "status": result.status,
                        "exitCode": result.exit_code if result.exit_code is not None else -1,
                    },
                    subject={"runId": run_id, "taskId": action.task_id},
                )
        return TaskExecutionOutcome(status="failed" if failed else "completed", results=results)

    def _derive_actions(self, task: "ExecutionTask") -> list[ExecutionAction]:
        """Map *task* to zero or more actions (S1 category heuristic).

        ``"validation"`` tasks whose description names a known tool
        (pytest/ruff/npm/python) become a ``run_validation`` action.
        ``"implementation"`` tasks become a ``create_file`` action recording
        the task under ``.autodev/execution-notes/`` — the current coder
        agent produces a component/description pair, not real code, so this
        is an honest record of real work rather than fabricated source.
        Every other category (planning/analysis/architecture/operations)
        derives no action yet.
        """
        if task.category == "validation":
            command = _extract_validation_command(task.description)
            if command is None:
                return []
            return [
                ExecutionAction(
                    action_id=f"{task.task_id}-validate",
                    type=ExecutionActionType.RUN_VALIDATION,
                    task_id=task.task_id,
                    step_key=task.task_id,
                    command=command,
                    cwd=".",
                )
            ]
        if task.category == "implementation":
            note_path = f".autodev/execution-notes/{task.task_id}.md"
            content = f"# {task.title}\n\n{task.description}\n"
            return [
                ExecutionAction(
                    action_id=f"{task.task_id}-note",
                    type=ExecutionActionType.CREATE_FILE,
                    task_id=task.task_id,
                    step_key=task.task_id,
                    path=note_path,
                    content=content,
                )
            ]
        return []


__all__ = ["TaskExecutor", "TaskExecutionOutcome"]
