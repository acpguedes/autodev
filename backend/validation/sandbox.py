"""Flag-gated validation sandbox runner.

Execution is disabled by default.  Set the environment variable
``AUTODEV_ENABLE_SANDBOX`` (any non-empty value) to enable it.

When enabled the runner prefers Docker if ``docker`` is on PATH; falls back to
a local ``subprocess.run`` call otherwise.

Optional command allowlist
--------------------------
Instantiate ``SandboxRunner`` with an explicit *allowed_commands* list to
restrict which executables are permitted.  The check is against the first
element of ``ValidationJob.command``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Sequence

from backend.validation.models import ValidationJob, ValidationResult

# Default allowlist used when none is supplied.  All entries are allow-listed
# by their base name so callers can pass full paths.
_DEFAULT_ALLOWED: frozenset[str] = frozenset(
    {"pytest", "ruff", "npm", "python", "python3"}
)

# Docker image used for sandboxed execution.
_DOCKER_IMAGE = "python:3.11-slim"


class SandboxRunner:
    """Execute :class:`ValidationJob` commands in a safe, flag-gated manner."""

    def __init__(
        self,
        allowed_commands: Sequence[str] | None = None,
    ) -> None:
        if allowed_commands is None:
            self._allowed: frozenset[str] = _DEFAULT_ALLOWED
        else:
            self._allowed = frozenset(allowed_commands)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, job: ValidationJob) -> ValidationResult:
        """Execute *job* and return a :class:`ValidationResult`.

        Returns a *skipped* result (no subprocess is spawned) when the
        ``AUTODEV_ENABLE_SANDBOX`` environment variable is not set.
        """
        if not os.environ.get("AUTODEV_ENABLE_SANDBOX"):
            return ValidationResult(
                job_id=job.job_id,
                returncode=0,
                stdout="",
                stderr="",
                backend="disabled",
                skipped=True,
            )

        if self._allowed:
            exe = os.path.basename(job.command[0]) if job.command else ""
            if exe not in self._allowed:
                return ValidationResult(
                    job_id=job.job_id,
                    returncode=1,
                    stdout="",
                    stderr=f"Command '{exe}' is not in the allowed list.",
                    backend="blocked",
                    skipped=True,
                )

        if shutil.which("docker"):
            return self._run_docker(job)
        return self._run_local(job)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_docker(self, job: ValidationJob) -> ValidationResult:
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-w",
            "/workspace",
            _DOCKER_IMAGE,
        ] + list(job.command)

        completed = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
        )
        return ValidationResult(
            job_id=job.job_id,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            backend="docker",
            skipped=False,
        )

    def _run_local(self, job: ValidationJob) -> ValidationResult:
        completed = subprocess.run(
            job.command,
            capture_output=True,
            text=True,
            cwd=job.cwd,
        )
        return ValidationResult(
            job_id=job.job_id,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            backend="local",
            skipped=False,
        )


__all__ = ["SandboxRunner"]
