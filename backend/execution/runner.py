"""Runners that dispatch :class:`ExecutionAction` to real backends (E14-S1).

:class:`InProcessActionRunner` is the S1 runner: it reuses the existing E0
patch engine (:mod:`backend.patches.engine`) for file/patch actions and the
v1 ``SandboxRunner`` precursor (:mod:`backend.validation.sandbox`) for
command/validation actions, per ADR-021. E14-S4 replaces/hardens this with
three dedicated runners behind the same :class:`ActionRunner` protocol; the
contract does not change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from backend.execution.contracts import ExecutionAction, ExecutionActionType, ExecutionResult
from backend.patches.engine import apply_patch, generate_patch
from backend.patches.models import Patch
from backend.validation.models import ValidationJob
from backend.validation.sandbox import SandboxRunner


class ActionRunner(Protocol):
    """Executes one :class:`ExecutionAction` and reports its outcome."""

    def run(self, action: ExecutionAction) -> ExecutionResult:
        """Execute *action* and return its :class:`ExecutionResult`."""
        ...


def _timestamp() -> str:
    """Return the current UTC time in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


class InProcessActionRunner:
    """Dispatches actions to the existing patch engine and sandbox runner."""

    def __init__(
        self,
        *,
        project_root: Path,
        sandbox_runner: SandboxRunner | None = None,
        enable_writes: bool | None = None,
    ) -> None:
        """Initialize the runner.

        Args:
            project_root: Root every file/patch action's target must resolve
                inside of (path-traversal guard).
            sandbox_runner: Sandbox used for command/validation actions;
                defaults to a settings-derived :class:`SandboxRunner`
                (fail-closed, disabled unless ``AUTODEV_ENABLE_SANDBOX=1``).
            enable_writes: Explicit override for whether file/patch writes
                are applied; ``None`` (default) consults
                ``AUTODEV_ENABLE_PATCH_APPLY`` (fail-closed).
        """
        self._project_root = project_root
        self._sandbox_runner = sandbox_runner or SandboxRunner()
        self._enable_writes = enable_writes

    def run(self, action: ExecutionAction) -> ExecutionResult:
        """Execute *action* and return its :class:`ExecutionResult`."""
        started_at = _timestamp()
        if action.type in (ExecutionActionType.CREATE_FILE, ExecutionActionType.EDIT_FILE):
            return self._run_file_action(action, started_at)
        if action.type is ExecutionActionType.APPLY_PATCH:
            return self._run_patch_action(action, started_at)
        return self._run_sandbox_action(action, started_at)

    def _run_file_action(self, action: ExecutionAction, started_at: str) -> ExecutionResult:
        """Build and apply a patch from ``action.path``/``action.content``."""
        assert action.path is not None
        resolved_root = self._project_root.resolve()
        target = (resolved_root / action.path).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            return self._failed(
                action,
                started_at,
                error=f"Path traversal rejected: {action.path!r} resolves outside root.",
            )
        try:
            original = target.read_text(encoding="utf-8") if target.exists() else ""
        except OSError as exc:
            return self._failed(action, started_at, error=str(exc))
        patch = generate_patch(action.path, original, action.content or "")
        return self._apply(action, patch, started_at)

    def _run_patch_action(self, action: ExecutionAction, started_at: str) -> ExecutionResult:
        """Apply a pre-built :class:`Patch` via the E0 patch engine."""
        assert action.patch is not None
        return self._apply(action, action.patch, started_at)

    def _apply(self, action: ExecutionAction, patch: Patch, started_at: str) -> ExecutionResult:
        """Run :func:`apply_patch` and translate its outcome into a result."""
        try:
            result = apply_patch(patch, root=str(self._project_root), enable=self._enable_writes)
        except ValueError as exc:
            return self._failed(action, started_at, error=str(exc), diff=patch.diff)
        return ExecutionResult(
            action_id=action.action_id,
            task_id=action.task_id,
            step_key=action.step_key,
            status="succeeded",
            started_at=started_at,
            completed_at=_timestamp(),
            stdout=result.message,
            diff=patch.diff,
            artifacts=[result.path] if result.applied else [],
        )

    def _run_sandbox_action(self, action: ExecutionAction, started_at: str) -> ExecutionResult:
        """Wrap the action into a :class:`ValidationJob` and dispatch to the sandbox."""
        job = ValidationJob(job_id=action.action_id, command=action.command or [], cwd=action.cwd)
        validation_result = self._sandbox_runner.run(job)
        succeeded = validation_result.returncode == 0
        return ExecutionResult(
            action_id=action.action_id,
            task_id=action.task_id,
            step_key=action.step_key,
            status="succeeded" if succeeded else "failed",
            started_at=started_at,
            completed_at=_timestamp(),
            stdout=validation_result.stdout,
            stderr=validation_result.stderr,
            exit_code=validation_result.returncode,
            error=None if succeeded else validation_result.stderr,
        )

    def _failed(
        self,
        action: ExecutionAction,
        started_at: str,
        *,
        error: str,
        diff: str = "",
    ) -> ExecutionResult:
        """Build a failed :class:`ExecutionResult` for *action*."""
        return ExecutionResult(
            action_id=action.action_id,
            task_id=action.task_id,
            step_key=action.step_key,
            status="failed",
            started_at=started_at,
            completed_at=_timestamp(),
            diff=diff,
            error=error,
        )


__all__ = ["ActionRunner", "InProcessActionRunner"]
