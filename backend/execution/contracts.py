"""Contracts for real task execution (E14-S1, RFC-009/ADR-021).

Defines the :class:`ExecutionAction` / :class:`ExecutionResult` pair that
:class:`backend.execution.executor.TaskExecutor` uses to turn an
``ExecutionTask`` into real, auditable work.
"""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Fallback StrEnum compatible with Python 3.10."""

        pass


from dataclasses import dataclass, field
from typing import Any

from backend.patches.models import Patch


class ExecutionActionType(StrEnum):
    """Kinds of real work an :class:`ExecutionAction` can perform."""

    CREATE_FILE = "create_file"
    EDIT_FILE = "edit_file"
    APPLY_PATCH = "apply_patch"
    RUN_COMMAND = "run_command"
    RUN_VALIDATION = "run_validation"


@dataclass(frozen=True, slots=True)
class ExecutionAction:
    """One unit of real work derived from an ``ExecutionTask``.

    Attributes:
        action_id: Unique identifier for this action.
        type: The kind of work to perform.
        task_id: Identifier of the ``ExecutionTask`` this action was derived from.
        step_key: Run-step key this action's outcome is reported under.
        path: Target file path, for ``create_file``/``edit_file``.
        content: New file content, for ``create_file``/``edit_file``.
        patch: Pre-built patch to apply, for ``apply_patch``.
        command: Command to execute, for ``run_command``/``run_validation``.
        cwd: Working directory for ``command``, relative to the project root.
        step_label: The originating task's plain-language title (E43-S3),
            e.g. "Implement Main Application File" -- carried alongside the
            technical ``task_id`` so a transcript renderer can show "Creating
            main.py" instead of a bare id like ``coding-file-1``.
    """

    action_id: str
    type: ExecutionActionType
    task_id: str
    step_key: str
    path: str | None = None
    content: str | None = None
    patch: Patch | None = None
    command: list[str] | None = None
    cwd: str = "."
    step_label: str | None = None


@dataclass(slots=True)
class ExecutionResult:
    """Outcome of running one :class:`ExecutionAction`.

    Attributes:
        action_id: Identifier of the action this result belongs to.
        task_id: Identifier of the originating ``ExecutionTask``.
        step_key: Run-step key this result is reported under.
        status: ``"succeeded"`` or ``"failed"``.
        started_at: ISO-8601 timestamp when the action started.
        completed_at: ISO-8601 timestamp when the action completed.
        stdout: Captured standard output, if any.
        stderr: Captured standard error, if any.
        exit_code: Process exit code, when the action ran a command.
        diff: Unified diff produced by a file/patch action, if any.
        artifacts: Paths of files actually written by this action.
        error: Human-readable error, set only when ``status == "failed"``.
        environment: The resolved execution-environment identity this
            action ran under (E32-S4-T1): ``{"environmentId", "backendKind",
            "profileHash"}`` when the action was dispatched through a
            bound environment, or ``{}`` when none was bound (e.g. direct
            E14 construction without E32 wiring -- fully backward compatible).
        command: The real command that was run, for ``run_command``/
            ``run_validation`` actions (E43-S2) -- lets a transcript
            renderer show the actual ``$ pytest -q`` line instead of only
            the task's plain-language description.
        path: The file target that was written, for ``create_file``/
            ``edit_file``/``apply_patch`` actions (E43-S2).
    """

    action_id: str
    task_id: str
    step_key: str
    status: str
    started_at: str
    completed_at: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    diff: str = ""
    artifacts: list[str] = field(default_factory=list)
    error: str | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    command: list[str] | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render this result as a plain, JSON-safe dict."""
        return {
            "action_id": self.action_id,
            "task_id": self.task_id,
            "step_key": self.step_key,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "diff": self.diff,
            "artifacts": list(self.artifacts),
            "error": self.error,
            "environment": dict(self.environment),
            "command": list(self.command) if self.command is not None else None,
            "path": self.path,
        }


__all__ = ["ExecutionActionType", "ExecutionAction", "ExecutionResult"]
