"""Data models for the sandbox validation runner."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationJob:
    """Describes a validation command to execute.

    Attributes:
        job_id: Unique identifier for this job.
        command: The command and its arguments.
        cwd: Working directory, relative to the sandbox policy's project root.
        extra_env: Additional environment variables to inject into the
            command's process (e.g. resolved secret values, E33-S2). Never
            logged or included in any persisted record -- it exists only to
            be handed to the subprocess call.
    """

    job_id: str
    command: list[str]
    cwd: str = "."
    extra_env: dict[str, str] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Outcome of a validation run (or a skipped/disabled run).

    Attributes:
        failure_kind: Typed reason this run failed (E46-S1, ADR-023), as
            the raw string value of an
            :class:`backend.execution.contracts.ExecutionFailureKind` --
            kept as a plain string here (not the enum) since this module
            sits below ``backend.execution`` and must not depend back on
            it. ``None`` for a successful or skipped-because-disabled run.
    """

    job_id: str
    returncode: int
    stdout: str
    stderr: str
    backend: str
    skipped: bool
    failure_kind: str | None = None


__all__ = ["ValidationJob", "ValidationResult"]
