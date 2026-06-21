"""Data models for the patch engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Patch:
    """Represents a pending file change as a unified diff."""

    path: str
    original: str
    updated: str
    diff: str


@dataclass
class PatchResult:
    """Outcome of applying (or dry-running) a patch."""

    path: str
    applied: bool
    dry_run: bool
    message: str


__all__ = ["Patch", "PatchResult"]
