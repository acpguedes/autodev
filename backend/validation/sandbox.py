"""Flag-gated validation sandbox runner.

Execution is disabled by default. Set ``AUTODEV_ENABLE_SANDBOX=1`` (or inject
an explicit :class:`SandboxPolicy` with ``enabled=True``) to enable it.

When enabled the runner prefers Docker if ``docker`` is on PATH and runs the
command in a hardened, read-only container (no network by default, non-root,
dropped capabilities, resource caps, a guarded read-only workspace mount) via
:func:`sandbox_policy_from_settings`. If Docker is unavailable it fails closed
unless the operator opts in to unsandboxed host execution via
``AUTODEV_SANDBOX_ALLOW_LOCAL``.

Optional command allowlist
--------------------------
Instantiate ``SandboxRunner`` with an explicit *allowed_commands* list to
restrict which executables are permitted. The check is against the first
element of ``ValidationJob.command`` -- after stripping a leading
``cd <dir> && ...``/``cd <dir>; ...`` prefix, if present, onto ``cwd``
(E43-S1).
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from opentelemetry import trace

from backend.config.settings import Settings, get_settings
from backend.observability.context import sanitize_identifier
from backend.observability.tracing import trace_dependency
from backend.validation.models import ValidationJob, ValidationResult

# Default allowlist used when none is supplied. All entries are allow-listed
# by their base name so callers can pass full paths.
_DEFAULT_ALLOWED: frozenset[str] = frozenset(
    {"pytest", "ruff", "npm", "python", "python3"}
)

# Docker image used for sandboxed execution.
_DOCKER_IMAGE = "python:3.11-slim"

# Timeout is mapped onto the shell/`timeout(1)` convention for a killed process.
_TIMEOUT_RETURNCODE = 124

# Chain separators a `cd <dir> && <cmd>` / `cd <dir>; <cmd>` prefix may use,
# either as their own token or attached to the directory token (both are
# produced by upstream naive whitespace tokenization -- see _strip_cd_prefix).
_CD_CHAIN_SEPARATORS = ("&&", ";")


@dataclass(frozen=True)
class SandboxPolicy:
    """Typed, immutable execution policy for the current Docker sandbox.

    Attributes:
        enabled: Whether sandboxed execution is enabled at all.
        allow_local: Whether unsandboxed host execution is permitted when
            Docker is unavailable.
        docker_network: Docker ``--network`` value; ``"none"`` by default.
        project_root: Absolute root every job's working directory must resolve
            inside of.
        timeout_seconds: Maximum wall-clock duration for one job.
    """

    enabled: bool
    allow_local: bool
    docker_network: str
    project_root: Path
    timeout_seconds: int


class SandboxPolicyError(ValueError):
    """Raised when a validation job violates the sandbox policy."""


def sandbox_policy_from_settings(settings: Settings | None = None) -> SandboxPolicy:
    """Build the current Docker sandbox policy from typed settings.

    Args:
        settings: Optional settings instance; defaults to the cached settings.

    Returns:
        An immutable sandbox policy.
    """
    active = settings or get_settings()
    project_root = Path(active.autodev_project_root.strip() or ".").expanduser().resolve()
    return SandboxPolicy(
        enabled=active.autodev_enable_sandbox,
        allow_local=active.autodev_sandbox_allow_local,
        docker_network=(active.autodev_sandbox_docker_network.strip() or "none"),
        project_root=project_root,
        timeout_seconds=active.autodev_sandbox_timeout_seconds,
    )


class SandboxRunner:
    """Execute :class:`ValidationJob` commands in a safe, flag-gated manner."""

    def __init__(
        self,
        allowed_commands: Sequence[str] | None = None,
        *,
        policy: SandboxPolicy | None = None,
    ) -> None:
        """Initialize a runner with an explicit or settings-derived policy.

        Args:
            allowed_commands: Executables permitted to run; defaults to a safe
                built-in allowlist.
            policy: Explicit sandbox policy; defaults to
                :func:`sandbox_policy_from_settings`.
        """
        self._allowed: frozenset[str] = (
            _DEFAULT_ALLOWED if allowed_commands is None else frozenset(allowed_commands)
        )
        self._policy = policy or sandbox_policy_from_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, job: ValidationJob) -> ValidationResult:
        """Execute *job* and return a :class:`ValidationResult`.

        Returns a *skipped* result (no subprocess is spawned) when the sandbox
        policy is disabled, the command is not allowlisted, or ``job.cwd``
        escapes the guarded workspace.
        """
        with trace_dependency(kind="sandbox", name="validation") as dependency_trace:
            result = self._execute(job)
            trace.get_current_span().set_attribute(
                "autodev.sandbox.backend", sanitize_identifier(result.backend)
            )
            if result.skipped:
                status = "skipped"
            elif result.returncode == 0:
                status = "success"
            else:
                status = "failed"
            if result.backend == "blocked":
                error_code = "command_blocked"
            elif result.backend == "unavailable":
                error_code = "sandbox_unavailable"
            elif status == "failed":
                error_code = "validation_failed"
            else:
                error_code = ""
            dependency_trace.finish(status=status, error_code=error_code)
            return result

    def _execute(self, job: ValidationJob) -> ValidationResult:
        """Execute the current sandbox policy inside dependency tracing.

        Args:
            job: Validation command and working directory.

        Returns:
            The bounded validation result.
        """
        if not self._policy.enabled:
            return ValidationResult(
                job_id=job.job_id,
                returncode=0,
                stdout="",
                stderr="",
                backend="disabled",
                skipped=True,
            )

        job = self._strip_cd_prefix(job)

        if self._allowed:
            exe = job.command[0].rsplit("/", 1)[-1] if job.command else ""
            if exe not in self._allowed:
                return ValidationResult(
                    job_id=job.job_id,
                    returncode=1,
                    stdout="",
                    stderr=f"Command '{exe}' is not in the allowed list.",
                    backend="blocked",
                    skipped=True,
                )

        try:
            workspace = self._resolve_workspace(job.cwd)
        except SandboxPolicyError as exc:
            return ValidationResult(
                job_id=job.job_id,
                returncode=1,
                stdout="",
                stderr=str(exc),
                backend="blocked",
                skipped=True,
            )

        if shutil.which("docker"):
            return self._run_docker(job, workspace)

        # Fail closed: without Docker there is no isolation. Running directly on
        # the host is only permitted when the operator explicitly opts in via
        # the policy's allow_local flag, so the default deployment cannot be
        # tricked into unsandboxed host execution.
        if self._policy.allow_local:
            return self._run_local(job, workspace)

        return ValidationResult(
            job_id=job.job_id,
            returncode=1,
            stdout="",
            stderr=(
                "Docker is not available and unsandboxed local execution is "
                "disabled. Install Docker or set AUTODEV_SANDBOX_ALLOW_LOCAL=1 "
                "to run commands directly on the host (unsafe)."
            ),
            backend="unavailable",
            skipped=True,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _strip_cd_prefix(self, job: ValidationJob) -> ValidationJob:
        """Fold a leading ``cd <dir> && <cmd>`` / ``cd <dir>; <cmd>`` prefix into *job*.

        Agent-declared commands (E41-S4 structured output) naturally arrive
        this way instead of using ``job.cwd`` directly, and are tokenized
        upstream with plain whitespace splitting rather than shell-aware
        parsing -- so the chain separator may be its own token
        (``["cd", "dir", "&&", "pytest"]``) or glued onto the directory
        (``["cd", "dir;", "pytest"]``). Defense in depth: the sandbox already
        accepts an explicit working directory (E43-S1-T1), so this only
        handles the compound form that still slips through, folding it into
        the same ``cwd``/``command`` shape the runner already guards -- it
        does not loosen the workspace-containment or allowlist checks that
        follow.

        Args:
            job: The job as declared by the caller.

        Returns:
            *job* unchanged if no ``cd`` prefix is present; otherwise a copy
            with ``cwd`` set to the ``cd`` target and ``command`` set to the
            real command that follows it.
        """
        command = job.command
        if len(command) < 2 or command[0] != "cd":
            return job

        cd_path = command[1]
        rest = command[2:]
        for sep in _CD_CHAIN_SEPARATORS:
            if cd_path.endswith(sep):
                cd_path = cd_path[: -len(sep)]
                real_command = rest
                break
        else:
            if rest and rest[0] in _CD_CHAIN_SEPARATORS:
                real_command = rest[1:]
            else:
                return job

        if not cd_path or not real_command:
            return job
        return dataclasses.replace(job, command=list(real_command), cwd=cd_path)

    def _resolve_workspace(self, cwd: str) -> Path:
        """Resolve and guard a job's working directory against the policy root.

        Args:
            cwd: Requested working directory, absolute or relative to the
                policy's project root.

        Returns:
            The resolved, existing directory, guaranteed to sit inside
            ``self._policy.project_root``.

        Raises:
            SandboxPolicyError: If the directory escapes the project root,
                does not exist, or is not a directory.
        """
        candidate = Path(cwd).expanduser()
        if not candidate.is_absolute():
            candidate = self._policy.project_root / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise SandboxPolicyError("validation cwd does not exist") from exc
        try:
            resolved.relative_to(self._policy.project_root)
        except ValueError as exc:
            raise SandboxPolicyError(
                "validation cwd is outside AUTODEV_PROJECT_ROOT"
            ) from exc
        if not resolved.is_dir():
            raise SandboxPolicyError("validation cwd must be a directory")
        return resolved

    def _run_docker(self, job: ValidationJob, workspace: Path) -> ValidationResult:
        # Harden the container: no network by default, non-root, dropped
        # capabilities, no privilege escalation, resource caps, a read-only
        # root filesystem with a bounded scratch /tmp, and a read-only bind
        # mount of only the guarded workspace (never the whole host). Network
        # can be re-enabled per-deployment via the policy's docker_network for
        # workloads that legitimately need it (e.g. dependency installs).
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            f"--network={self._policy.docker_network}",
            "--user=65534:65534",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=256",
            "--memory=512m",
            "--cpus=1",
            "--read-only",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=256m",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            *(f"--env={name}={value}" for name, value in job.extra_env.items()),
            "--mount",
            f"type=bind,source={workspace},target=/workspace,readonly",
            "--workdir=/workspace",
            _DOCKER_IMAGE,
            *job.command,
        ]

        try:
            completed = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self._policy.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ValidationResult(
                job_id=job.job_id,
                returncode=_TIMEOUT_RETURNCODE,
                stdout="",
                stderr=f"validation timed out after {self._policy.timeout_seconds}s",
                backend="docker",
                skipped=False,
            )
        return ValidationResult(
            job_id=job.job_id,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            backend="docker",
            skipped=False,
        )

    def _run_local(self, job: ValidationJob, workspace: Path) -> ValidationResult:
        env = {**os.environ, **job.extra_env} if job.extra_env else None
        try:
            completed = subprocess.run(
                job.command,
                capture_output=True,
                text=True,
                cwd=workspace,
                timeout=self._policy.timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ValidationResult(
                job_id=job.job_id,
                returncode=_TIMEOUT_RETURNCODE,
                stdout="",
                stderr=f"validation timed out after {self._policy.timeout_seconds}s",
                backend="local",
                skipped=False,
            )
        return ValidationResult(
            job_id=job.job_id,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            backend="local",
            skipped=False,
        )


__all__ = ["SandboxPolicy", "SandboxPolicyError", "SandboxRunner", "sandbox_policy_from_settings"]
