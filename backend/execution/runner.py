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
from typing import TYPE_CHECKING, Optional, Protocol

from backend.execution.contracts import (
    ExecutionAction,
    ExecutionActionType,
    ExecutionFailureKind,
    ExecutionResult,
)
from backend.patches.engine import apply_patch, generate_patch
from backend.patches.models import Patch
from backend.validation.models import ValidationJob
from backend.validation.sandbox import SandboxRunner

if TYPE_CHECKING:
    from backend.environments.contracts import EnvironmentHandle
    from backend.environments.manager import EnvironmentManager


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


def _run_via_sandbox(
    action: ExecutionAction,
    sandbox_runner: SandboxRunner,
    started_at: str,
    *,
    extra_env: Optional[dict[str, str]] = None,
) -> ExecutionResult:
    """Wrap *action* into a :class:`ValidationJob` and dispatch to *sandbox_runner*.

    Shared by :class:`CommandRunner` and :class:`ValidationRunner` — both
    reuse the same hardened, flag-gated sandbox; only the action type each
    accepts differs.

    Args:
        extra_env: Environment variables to inject into the job's process
            (E33-S2) — e.g. secrets resolved for an environment-bound
            dispatch. ``None``/empty for the default (unbound) path.
    """
    job = ValidationJob(
        job_id=action.action_id,
        command=action.command or [],
        cwd=action.cwd,
        extra_env=extra_env or {},
    )
    validation_result = sandbox_runner.run(job)
    succeeded = validation_result.returncode == 0
    if succeeded:
        failure_kind = None
    elif validation_result.failure_kind:
        failure_kind = ExecutionFailureKind(validation_result.failure_kind)
    else:
        # Process exit codes default to code_failure (ADR-023): an
        # unclassified failure from any ValidationResult producer is still
        # a safe, repair-eligible default rather than silently dropped.
        failure_kind = ExecutionFailureKind.CODE_FAILURE
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
        command=list(action.command) if action.command else None,
        failure_kind=failure_kind,
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
            path=action.path or patch.path,
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


def _action_target_path(action: ExecutionAction) -> str:
    """Return the filesystem/cwd target an action's environment check applies to."""
    if action.type is ExecutionActionType.APPLY_PATCH and action.patch is not None:
        return action.patch.path
    if action.path is not None:
        return action.path
    return action.cwd


class CompositeActionRunner:
    """Dispatches each action to the dedicated runner for its type (E14-S4).

    Optionally environment-aware (E32-S1-T1): when bound to a provisioned
    :class:`~backend.environments.contracts.EnvironmentHandle` via
    :meth:`bind_environment`, every dispatch is first checked against the
    environment's fail-closed filesystem policy, and ``run_command``/
    ``run_validation`` actions dispatch through the environment-scoped
    sandbox rather than the fixed default -- every resulting
    :class:`~backend.execution.contracts.ExecutionResult` names the
    environment it ran under. Unbound (the default), behavior is
    unchanged from E14-S4.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        sandbox_runner: Optional[SandboxRunner] = None,
        enable_writes: Optional[bool] = None,
        environment_manager: Optional["EnvironmentManager"] = None,
    ) -> None:
        """Initialize the composite runner and its three dedicated runners.

        Args:
            project_root: Root every file/patch action's target must resolve
                inside of (path-traversal guard) — forwarded to :class:`PatchRunner`.
            sandbox_runner: Sandbox shared by :class:`CommandRunner` and
                :class:`ValidationRunner`; defaults to a settings-derived
                :class:`SandboxRunner` (fail-closed, disabled unless
                ``AUTODEV_ENABLE_SANDBOX=1``). Used only while no
                environment is bound.
            enable_writes: Explicit override for whether file/patch writes
                are applied; ``None`` (default) consults
                ``AUTODEV_ENABLE_PATCH_APPLY`` (fail-closed). Forwarded to
                :class:`PatchRunner`.
            environment_manager: Optional E32 environment manager; when
                given, :meth:`bind_environment` can scope dispatch to a
                provisioned environment (E32-S1-T1).
        """
        shared_sandbox = sandbox_runner or SandboxRunner()
        self._patch_runner = PatchRunner(project_root=project_root, enable_writes=enable_writes)
        self._command_runner = CommandRunner(sandbox_runner=shared_sandbox)
        self._validation_runner = ValidationRunner(sandbox_runner=shared_sandbox)
        self._environment_manager = environment_manager
        self._environment_handle: Optional["EnvironmentHandle"] = None
        self._environment_extra_env: dict[str, str] = {}

    def bind_environment(self, handle: Optional["EnvironmentHandle"]) -> None:
        """Scope subsequent dispatches to a provisioned environment, or clear the binding.

        Resolves the profile's allowlisted secrets once per binding
        (E33-S2-T1) rather than once per dispatched action, so a batch of
        several actions against the same environment triggers one
        resolution pass, not one per action.

        Args:
            handle: The environment to scope dispatch to; ``None`` reverts
                to the default (unbound) behavior.

        Raises:
            RuntimeError: If *handle* is given but no ``environment_manager``
                was supplied at construction.
        """
        if handle is not None and self._environment_manager is None:
            raise RuntimeError("bind_environment requires an environment_manager")
        self._environment_handle = handle
        self._environment_extra_env = (
            self._environment_manager.resolve_secrets_for_profile(handle)
            if handle is not None and self._environment_manager is not None
            else {}
        )

    def _environment_metadata(self) -> dict[str, str]:
        handle = self._environment_handle
        if handle is None:
            return {}
        return {
            "environmentId": handle.environment_id,
            "backendKind": handle.backend_kind.value,
            "profileHash": handle.profile.content_hash(),
        }

    def run(self, action: ExecutionAction) -> ExecutionResult:
        """Dispatch *action* to the runner for its type and return the result."""
        handle = self._environment_handle
        if handle is not None:
            assert self._environment_manager is not None  # guaranteed by bind_environment
            denial = self._environment_manager.evaluate_filesystem(
                handle, path=_action_target_path(action)
            )
            if denial is not None:
                now = datetime.now(timezone.utc).isoformat()
                result = ExecutionResult(
                    action_id=action.action_id,
                    task_id=action.task_id,
                    step_key=action.step_key,
                    status="failed",
                    started_at=now,
                    completed_at=now,
                    error=f"environment policy denied: {denial.reason}",
                    failure_kind=ExecutionFailureKind.POLICY_DENIED,
                )
                result.environment = self._environment_metadata()
                return result

        if action.type in (
            ExecutionActionType.CREATE_FILE,
            ExecutionActionType.EDIT_FILE,
            ExecutionActionType.APPLY_PATCH,
        ):
            result = self._patch_runner.run(action)
        else:
            result = self._run_command_or_validation(action)
        result.environment = self._environment_metadata()
        return result

    def _run_command_or_validation(self, action: ExecutionAction) -> ExecutionResult:
        if self._environment_handle is not None:
            assert self._environment_manager is not None
            sandbox = self._environment_manager.command_sandbox(self._environment_handle)
            return _run_via_sandbox(
                action, sandbox, _timestamp(), extra_env=self._environment_extra_env
            )
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
