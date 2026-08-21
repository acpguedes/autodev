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

        Convenience wrapper over :meth:`derive_actions` + :meth:`dispatch`
        for callers that don't need to inspect actions before running them
        (E14-S1's original entry point; E14-S3's execution-mode gating in
        ``OrchestratorService`` calls the two steps separately).

        Args:
            task: The plan task to turn into real work.
            run_id: Orchestrator run this execution belongs to (event partition key).
            tenant_id: Tenant the run belongs to.
            actor: Who/what is driving this execution (audited by policy
                evaluations; defaults to ``"system"`` for automatic runs).

        Returns:
            The aggregate outcome across every action derived from *task*.
        """
        actions = self.derive_actions(task)
        return self.dispatch(actions, run_id=run_id, tenant_id=tenant_id, actor=actor)

    def dispatch(
        self,
        actions: list[ExecutionAction],
        *,
        run_id: str,
        tenant_id: str,
        actor: str = "system",
        pre_approved_action_ids: frozenset[str] = frozenset(),
    ) -> TaskExecutionOutcome:
        """Run already-derived *actions* and report the aggregate outcome.

        Args:
            actions: Actions to run, in order.
            run_id: Orchestrator run this execution belongs to (event partition key).
            tenant_id: Tenant the run belongs to.
            actor: Who/what is driving this execution (audited by policy
                evaluations; defaults to ``"system"`` for automatic runs).
            pre_approved_action_ids: Action ids that skip the policy gate
                entirely (E14-S3: a human already explicitly approved this
                specific action out of band — the human decision itself is
                the authorization, independent of whether a static or
                dynamic policy rule also covers it).

        Returns:
            The aggregate outcome across every action.
        """
        results: list[ExecutionResult] = []
        failed = False
        for action in actions:
            if self._policy is not None and action.action_id not in pre_approved_action_ids:
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

    def deny_all(
        self, actions: list[ExecutionAction], *, run_id: str, tenant_id: str, reason: str
    ) -> TaskExecutionOutcome:
        """Fail every action without dispatching to policy or the runner.

        Used by E14-S3 when a human decision denies a task, or a pending
        decision times out (deny-and-stop fallback) — the decision itself
        is the reason execution never reaches the runner.

        Args:
            actions: The actions the denied task derived.
            run_id: Orchestrator run this belongs to (event partition key).
            tenant_id: Tenant the run belongs to.
            reason: Human-readable denial reason, recorded on every result.

        Returns:
            A ``"failed"`` outcome covering every action.
        """
        results: list[ExecutionResult] = []
        for action in actions:
            now = _timestamp()
            result = ExecutionResult(
                action_id=action.action_id,
                task_id=action.task_id,
                step_key=action.step_key,
                status="failed",
                started_at=now,
                completed_at=now,
                error=reason,
            )
            results.append(result)
            emit_event(
                "execution.action.failed",
                tenant_id=tenant_id,
                partition_key=run_id,
                data={"actionId": action.action_id, "taskId": action.task_id, "error": reason},
                subject={"runId": run_id, "taskId": action.task_id},
            )
        return TaskExecutionOutcome(status="failed", results=results)

    def derive_actions(self, task: "ExecutionTask") -> list[ExecutionAction]:
        """Map *task* to zero or more actions.

        ``"validation"`` tasks prefer an agent-declared structured
        ``commands`` list (E41-S4, validator structured output) over
        keyword-sniffing free text; the keyword heuristic
        (pytest/ruff/npm/python) remains as the fallback only when no
        structured commands are present (stub/unconfigured-provider path).
        ``"operations"`` tasks likewise dispatch agent-declared
        ``commands`` (devops structured output) when present; they derive
        no action otherwise, unchanged from before E41. ``"implementation"``
        tasks that carry real file content (E41-S2, coder structured
        output) become one ``create_file`` action per file, dispatched
        through the same E0 patch engine (:mod:`backend.patches.engine`)
        the Patches API already uses (E41-S3) — real source, not a
        description. An "implementation" task with no file content falls
        back to recording the task under ``.autodev/execution-notes/``
        (pre-E41 coder output produces only a component/description pair,
        so this remains an honest record of real work rather than
        fabricated source). ``"planning"``/``"analysis"``/``"architecture"``
        derive no action yet.
        """
        if task.category == "validation":
            if task.commands:
                return [
                    ExecutionAction(
                        action_id=f"{task.task_id}-validate-{index}",
                        type=ExecutionActionType.RUN_VALIDATION,
                        task_id=task.task_id,
                        step_key=task.task_id,
                        command=command.split(),
                        cwd=".",
                    )
                    for index, command in enumerate(task.commands, start=1)
                ]
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
        if task.category == "operations":
            if task.commands:
                return [
                    ExecutionAction(
                        action_id=f"{task.task_id}-run-{index}",
                        type=ExecutionActionType.RUN_COMMAND,
                        task_id=task.task_id,
                        step_key=task.task_id,
                        command=command.split(),
                        cwd=".",
                    )
                    for index, command in enumerate(task.commands, start=1)
                ]
            return []
        if task.category == "implementation":
            if task.files:
                return [
                    ExecutionAction(
                        action_id=f"{task.task_id}-write-{index}",
                        type=ExecutionActionType.CREATE_FILE,
                        task_id=task.task_id,
                        step_key=task.task_id,
                        path=file_entry["path"],
                        content=file_entry["content"],
                    )
                    for index, file_entry in enumerate(task.files, start=1)
                ]
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
