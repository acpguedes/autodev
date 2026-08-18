"""Execution modes for plan execution (E14-S3).

Three modes govern how :class:`~backend.orchestrator.service.OrchestratorService`
handles a task with at least one derived action:

- ``AUTO``: policy (E14-S2) alone decides; no human is ever involved.
- ``APPROVAL``: every task with an action pauses for a human decision.
- ``HYBRID``: policy-covered actions auto-execute; uncovered ones pause with
  a 3-option decision (run once / always / deny).
"""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Fallback StrEnum compatible with Python 3.10."""

        pass


class ExecutionMode(StrEnum):
    """How a plan-execution run decides whether an action may proceed."""

    AUTO = "auto"
    APPROVAL = "approval"
    HYBRID = "hybrid"


class HybridDecision(StrEnum):
    """The 3 options offered when hybrid mode pauses on an uncovered action."""

    RUN_ONCE = "run_once"
    ALWAYS = "always"
    DENY = "deny"


__all__ = ["ExecutionMode", "HybridDecision"]
