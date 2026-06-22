"""Data models for the sandbox validation runner."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValidationJob:
    """Describes a validation command to execute."""

    job_id: str
    command: list[str]
    cwd: str = "."


@dataclass
class ValidationResult:
    """Outcome of a validation run (or a skipped/disabled run)."""

    job_id: str
    returncode: int
    stdout: str
    stderr: str
    backend: str
    skipped: bool


__all__ = ["ValidationJob", "ValidationResult"]
