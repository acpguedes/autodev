"""Runners that dispatch :class:`ExecutionAction` to real backends.

Three dedicated runners (E14-S4), split from the single S1 in-process
runner per ADR-021's own stated plan, each behind the same
:class:`ActionRunner` protocol:

- :class:`PatchRunner` — ``create_file``/``edit_file``/``apply_patch`` via
  the E0 patch engine (:mod:`backend.patches.engine`). Never falls back to
  arbitrary command execution — there is no code path from this class into
  ``subprocess``.
- :class:`CommandRunner` — ``run_command`` via the hardened v1
  ``SandboxRunner`` precursor (:mod:`backend.validation.sandbox`):
  no-network by default, allowlisted, fails closed without Docker.
- :class:`ValidationRunner` — ``run_validation``, reusing the same
  ``SandboxRunner``/existing Validation Gates.

:class:`CompositeActionRunner` dispatches by action type to the three
above. :data:`InProcessActionRunner` is a backward-compatible alias for it
(E14-S1's original name and constructor signature) — the contract does not
change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

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


def _failed(action: ExecutionAction, started_at: str, *, error: str, diff: str = "") -> ExecutionResult:
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


def _run_via_sandbox(action: ExecutionAction, sandbox_runner: SandboxRunner, started_at: str) -> ExecutionResult:
    """Wrap *action* into a :class:`ValidationJob` and dispatch to *sandbox_runner*.

    Shared by :class:`CommandRunner` and :class:`ValidationRunner` — both
    reuse the same hardened, flag-gated sandbox; only the action type each
    accepts differs.
    """
    job = ValidationJob(job_id=action.action_id, command=action.command or [], cwd=action.cwd)
    validation_result = sandbox_runner.run(job)
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


class PatchRunner:
    """Executes ``create_file``/``edit_file``/``apply_patch`` via the E0 patch engine.

    Structurally separate from :class:`CommandRunner`: this class never
    imports or calls ``subprocess`` — a file/patch action can only ever
    result in a guarded, patch-engine-mediated write, never arbitrary
    command execution.
    """

    def __init__(self, *, project_root: Path, enable_writes: Optional[bool] = None) -> None:
        """Initialize the runner.

        Args:
            project_root: Root every target must resolve inside of
                (path-traversal guard, re-checked before any read).
            enable_writes: Explicit override for whether writes are
                applied; ``None`` (default) consults
                ``AUTODEV_ENABLE_PATCH_APPLY`` (fail-closed).
        """
        self._project_root = project_root
        self._enable_writes = enable_writes

    def run(self, action: ExecutionAction) -> ExecutionResult:
        """Execute *action* and return its :class:`ExecutionResult`.

        Raises:
            ValueError: If ``action.type`` is not one this runner handles.
        """
        started_at = _timestamp()
        if action.type in (ExecutionActionType.CREATE_FILE, ExecutionActionType.EDIT_FILE):
            return self._run_file_action(action, started_at)
        if action.type is ExecutionActionType.APPLY_PATCH:
            return self._run_patch_action(action, started_at)
        raise ValueError(f"PatchRunner cannot run action type {action.type.value!r}")

    def _run_file_action(self, action: ExecutionAction, started_at: str) -> ExecutionResult:
        """Build and apply a patch from ``action.path``/``action.content``."""
        assert action.path is not None
        resolved_root = self._project_root.resolve()
        target = (resolved_root / action.path).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            return _failed(
                action,
                started_at,
                error=f"Path traversal rejected: {action.path!r} resolves outside root.",
            )
        try:
            original = target.read_text(encoding="utf-8") if target.exists() else ""
        except OSError as exc:
            return _failed(action, started_at, error=str(exc))
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
            return _failed(action, started_at, error=str(exc), diff=patch.diff)
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


class CommandRunner:
    """Executes ``run_command`` actions via the hardened v1 ``SandboxRunner``.

    No-network by default, allowlisted, fails closed without Docker unless
    the operator opts into unsandboxed local execution — unchanged from
    the sandbox's existing behavior; this class only narrows what dispatches
    to it (command actions only, never file/patch actions).
    """

    def __init__(self, *, sandbox_runner: Optional[SandboxRunner] = None) -> None:
        """Initialize the runner.

        Args:
            sandbox_runner: Sandbox to dispatch through; defaults to a
                settings-derived :class:`SandboxRunner`.
        """
        self._sandbox_runner = sandbox_runner or SandboxRunner()

    def run(self, action: ExecutionAction) -> ExecutionResult:
        """Execute *action* and return its :class:`ExecutionResult`.

        Raises:
            ValueError: If ``action.type`` is not ``run_command``.
        """
        if action.type is not ExecutionActionType.RUN_COMMAND:
            raise ValueError(f"CommandRunner cannot run action type {action.type.value!r}")
        return _run_via_sandbox(action, self._sandbox_runner, _timestamp())


class ValidationRunner:
    """Executes ``run_validation`` actions, reusing the existing Validation Gates.

    Shares the same hardened sandbox as :class:`CommandRunner` (both are
    ultimately "run this command safely"), kept as a distinct class per the
    story's 3-runner DoD so validation and arbitrary shell commands can be
    hardened independently in the future without touching each other.
    """

    def __init__(self, *, sandbox_runner: Optional[SandboxRunner] = None) -> None:
        """Initialize the runner.

        Args:
            sandbox_runner: Sandbox to dispatch through; defaults to a
                settings-derived :class:`SandboxRunner`.
        """
        self._sandbox_runner = sandbox_runner or SandboxRunner()

    def run(self, action: ExecutionAction) -> ExecutionResult:
        """Execute *action* and return its :class:`ExecutionResult`.

        Raises:
            ValueError: If ``action.type`` is not ``run_validation``.
        """
        if action.type is not ExecutionActionType.RUN_VALIDATION:
            raise ValueError(f"ValidationRunner cannot run action type {action.type.value!r}")
        return _run_via_sandbox(action, self._sandbox_runner, _timestamp())


class CompositeActionRunner:
    """Dispatches each action to the dedicated runner for its type (E14-S4)."""

    def __init__(
        self,
        *,
        project_root: Path,
        sandbox_runner: Optional[SandboxRunner] = None,
        enable_writes: Optional[bool] = None,
    ) -> None:
        """Initialize the composite runner and its three dedicated runners.

        Args:
            project_root: Root every file/patch action's target must resolve
                inside of (path-traversal guard) — forwarded to :class:`PatchRunner`.
            sandbox_runner: Sandbox shared by :class:`CommandRunner` and
                :class:`ValidationRunner`; defaults to a settings-derived
                :class:`SandboxRunner` (fail-closed, disabled unless
                ``AUTODEV_ENABLE_SANDBOX=1``).
            enable_writes: Explicit override for whether file/patch writes
                are applied; ``None`` (default) consults
                ``AUTODEV_ENABLE_PATCH_APPLY`` (fail-closed). Forwarded to
                :class:`PatchRunner`.
        """
        shared_sandbox = sandbox_runner or SandboxRunner()
        self._patch_runner = PatchRunner(project_root=project_root, enable_writes=enable_writes)
        self._command_runner = CommandRunner(sandbox_runner=shared_sandbox)
        self._validation_runner = ValidationRunner(sandbox_runner=shared_sandbox)

    def run(self, action: ExecutionAction) -> ExecutionResult:
        """Dispatch *action* to the runner for its type and return the result."""
        if action.type in (
            ExecutionActionType.CREATE_FILE,
            ExecutionActionType.EDIT_FILE,
            ExecutionActionType.APPLY_PATCH,
        ):
            return self._patch_runner.run(action)
        if action.type is ExecutionActionType.RUN_COMMAND:
            return self._command_runner.run(action)
        return self._validation_runner.run(action)


#: Backward-compatible alias for E14-S1's original runner name and
#: constructor signature — now a thin composite over the three dedicated
#: runners split out in E14-S4 (ADR-021's own stated plan). The
#: `ExecutionAction`/`ExecutionResult` contract is unchanged.
InProcessActionRunner = CompositeActionRunner


__all__ = [
    "ActionRunner",
    "CommandRunner",
    "CompositeActionRunner",
    "InProcessActionRunner",
    "PatchRunner",
    "ValidationRunner",
]
