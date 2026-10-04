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

import inspect
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from backend.events.runtime import emit_event
from backend.execution.contracts import (
    ExecutionAction,
    ExecutionActionType,
    ExecutionFailureKind,
    ExecutionResult,
)
from backend.execution.policy import PolicyEvaluator
from backend.execution.runner import ActionRunner

if TYPE_CHECKING:
    from backend.orchestrator.service import ExecutionTask


_ACTION_OUTPUT_CHAR_CAP = 4000
"""Max length of stdout/stderr carried on one ``execution.action.*`` event (E43-S2).

Bounds a single SSE event's payload regardless of how much a command
captured; the tail is kept since that is usually a failure's relevant
output.
"""


def _capped_tail(text: str) -> str:
    """Tail-truncate *text* to :data:`_ACTION_OUTPUT_CHAR_CAP`."""
    return text[-_ACTION_OUTPUT_CHAR_CAP:] if len(text) > _ACTION_OUTPUT_CHAR_CAP else text


def _was_truncated(*streams: str) -> bool:
    """Whether any stream exceeded :data:`_ACTION_OUTPUT_CHAR_CAP` and lost its head (E64-S2)."""
    return any(len(stream) > _ACTION_OUTPUT_CHAR_CAP for stream in streams)


class _ChunkEmitter:
    """Emits ``execution.action.output`` events on safe boundaries (E64-S3-T3).

    Secret redaction runs inside ``emit_event`` per payload, so a secret split
    across two chunks would escape it. Text is therefore emitted only in whole
    lines; the unfinished tail is carried over until its newline arrives (or
    :meth:`flush` at process end). A line longer than the event cap is cut at
    its last whitespace -- secrets contain none -- never mid-token, and the
    final chunk is never held back. The terminal event still carries the
    complete output, redacted the same way.
    """

    def __init__(self, *, action_id: str, run_id: str, tenant_id: str, task_id: str) -> None:
        self._action_id = action_id
        self._run_id = run_id
        self._tenant_id = tenant_id
        self._task_id = task_id
        self._carry: dict[str, str] = {"stdout": "", "stderr": ""}
        self._seq = 0
        self._lock = threading.Lock()

    def feed(self, stream: str, text: str) -> None:
        """Buffer *text* and emit every completed line of *stream*."""
        with self._lock:
            buffered = self._carry[stream] + text
            cut = buffered.rfind("\n") + 1
            if cut == 0 and len(buffered) > _ACTION_OUTPUT_CHAR_CAP:
                window = buffered[:_ACTION_OUTPUT_CHAR_CAP]
                cut = max(window.rfind(" "), window.rfind("\t")) + 1 or _ACTION_OUTPUT_CHAR_CAP
            self._carry[stream] = buffered[cut:]
            self._emit(stream, buffered[:cut])

    def flush(self) -> None:
        """Emit whatever unfinished tail remains on either stream."""
        with self._lock:
            for stream in ("stdout", "stderr"):
                tail, self._carry[stream] = self._carry[stream], ""
                self._emit(stream, tail)

    def _emit(self, stream: str, text: str) -> None:
        for start in range(0, len(text), _ACTION_OUTPUT_CHAR_CAP):
            self._seq += 1
            emit_event(
                "execution.action.output",
                tenant_id=self._tenant_id,
                partition_key=self._run_id,
                data={
                    "actionId": self._action_id,
                    "stream": stream,
                    "chunk": text[start : start + _ACTION_OUTPUT_CHAR_CAP],
                    "seq": self._seq,
                },
                subject={"runId": self._run_id, "taskId": self._task_id},
            )


def _accepts_on_chunk(runner: ActionRunner) -> bool:
    """Whether *runner*'s ``run`` takes the optional ``on_chunk`` callback (E64-S3)."""
    try:
        return "on_chunk" in inspect.signature(runner.run).parameters
    except (TypeError, ValueError):  # pragma: no cover - uninspectable callable
        return False


def _file_name(path: str) -> str:
    """Return the final path segment, for a plain-language "Creating <file>" label (E43-S3)."""
    return path.rsplit("/", 1)[-1] or path


def _action_path(action: ExecutionAction) -> str | None:
    """Return the file target an action wrote, for transcript rendering (E43-S2)."""
    if action.path is not None:
        return action.path
    if action.patch is not None:
        return action.patch.path
    return None


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
                        failure_kind=ExecutionFailureKind.POLICY_DENIED,
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
                            "command": list(action.command) if action.command else None,
                            "path": _action_path(action),
                            "stepLabel": action.step_label,
                            "sourceAgent": action.source_agent,
                            "failureKind": ExecutionFailureKind.POLICY_DENIED.value,
                        },
                        subject={"runId": run_id, "taskId": action.task_id},
                    )
                    continue
            emit_event(
                "execution.action.started",
                tenant_id=tenant_id,
                partition_key=run_id,
                data={
                    "actionId": action.action_id,
                    "taskId": action.task_id,
                    "type": action.type.value,
                    "command": list(action.command) if action.command else None,
                    "path": _action_path(action),
                    "stepLabel": action.step_label,
                    "sourceAgent": action.source_agent,
                },
                subject={"runId": run_id, "taskId": action.task_id},
            )
            if _accepts_on_chunk(self._runner):
                emitter = _ChunkEmitter(
                    action_id=action.action_id,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    task_id=action.task_id,
                )
                result = self._runner.run(action, on_chunk=emitter.feed)  # type: ignore[call-arg]
                emitter.flush()
            else:
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
                        "command": list(result.command) if result.command else None,
                        "path": result.path,
                        "stdout": _capped_tail(result.stdout),
                        "stderr": _capped_tail(result.stderr),
                        "stepLabel": action.step_label,
                        "failureKind": result.failure_kind.value if result.failure_kind else None,
                        "sourceAgent": action.source_agent,
                        "exitCode": result.exit_code,
                        "truncated": _was_truncated(result.stdout, result.stderr),
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
                        "command": list(result.command) if result.command else None,
                        "path": result.path,
                        "stdout": _capped_tail(result.stdout),
                        "stderr": _capped_tail(result.stderr),
                        "stepLabel": action.step_label,
                        "sourceAgent": action.source_agent,
                        "truncated": _was_truncated(result.stdout, result.stderr),
                    },
                    subject={"runId": run_id, "taskId": action.task_id},
                )
        return TaskExecutionOutcome(status="failed" if failed else "completed", results=results)

    def deny_all(
        self,
        actions: list[ExecutionAction],
        *,
        run_id: str,
        tenant_id: str,
        reason: str,
        failure_kind: ExecutionFailureKind = ExecutionFailureKind.POLICY_DENIED,
    ) -> TaskExecutionOutcome:
        """Fail every action without dispatching to policy or the runner.

        Used by E14-S3 when a human decision denies a task, or a pending
        decision times out (deny-and-stop fallback) — the decision itself
        is the reason execution never reaches the runner. Also used by
        E32-S3/S4 when a batch's execution environment failed to
        provision.

        Args:
            actions: The actions the denied task derived.
            run_id: Orchestrator run this belongs to (event partition key).
            tenant_id: Tenant the run belongs to.
            reason: Human-readable denial reason, recorded on every result.
            failure_kind: Typed reason every result carries (E46-S1,
                ADR-023); defaults to ``POLICY_DENIED`` (the human-decision
                case) — callers denying for a different reason (e.g. an
                unavailable environment) pass the matching kind.

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
                failure_kind=failure_kind,
            )
            results.append(result)
            emit_event(
                "execution.action.failed",
                tenant_id=tenant_id,
                partition_key=run_id,
                data={
                    "actionId": action.action_id,
                    "taskId": action.task_id,
                    "error": reason,
                    "command": list(action.command) if action.command else None,
                    "path": _action_path(action),
                    "stepLabel": action.step_label,
                    "sourceAgent": action.source_agent,
                    "failureKind": failure_kind.value,
                },
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
                        step_label=task.title or None,
                        source_agent=task.source_agent,
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
                    step_label=task.title or None,
                    source_agent=task.source_agent,
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
                        step_label=task.title or None,
                        source_agent=task.source_agent,
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
                        step_label=f"Creating {_file_name(file_entry['path'])}",
                        source_agent=task.source_agent,
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
                    step_label=task.title or None,
                    source_agent=task.source_agent,
                )
            ]
        return []


__all__ = ["TaskExecutor", "TaskExecutionOutcome"]
