"""Dynamic routing and supervisor policy for the orchestrator.

This module is STANDALONE — it is NOT wired into the default ``/chat`` path.

Key exports:
- ``RunTypeRouter`` — maps each ``RunType`` to an ordered list of agent names.
- ``SupervisorPolicy`` — stateful supervisor deciding the next agent or stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from backend.orchestrator.service import (
    AgentGraphState,
    RunType,
)


# ---------------------------------------------------------------------------
# RunTypeRouter
# ---------------------------------------------------------------------------

# Default full linear order (mirrors OrchestratorConfig.agent_order).
_FULL_ORDER: List[str] = [
    "navigator",
    "analyzer",
    "architect",
    "coder",
    "devops",
    "validator",
    "responder",
]

_ROUTE_MAP: dict[RunType, List[str]] = {
    RunType.DOCUMENTATION_UPDATE: ["navigator", "analyzer", "responder"],
    RunType.VALIDATION_ONLY: ["navigator", "validator", "responder"],
    RunType.DEVOPS_CHANGE: ["navigator", "analyzer", "devops", "responder"],
    RunType.GREENFIELD_BOOTSTRAP: _FULL_ORDER,
    RunType.EXISTING_REPO_CHANGE: _FULL_ORDER,
    RunType.PLAN_EXECUTION: _FULL_ORDER,
}


class RunTypeRouter:
    """Maps each ``RunType`` to an ordered list of agent names."""

    def __init__(self, route_map: dict[RunType, List[str]] | None = None) -> None:
        self._map: dict[RunType, List[str]] = (
            dict(route_map) if route_map is not None else dict(_ROUTE_MAP)
        )

    def order_for(self, run_type: RunType) -> List[str]:
        """Return the agent execution order for *run_type*.

        Falls back to the full linear order for unmapped types.
        """
        return list(self._map.get(run_type, _FULL_ORDER))

    def all_routes(self) -> dict[RunType, List[str]]:
        """Return a copy of the entire route mapping."""
        return dict(self._map)


# ---------------------------------------------------------------------------
# SupervisorPolicy
# ---------------------------------------------------------------------------


@dataclass
class SupervisorPolicy:
    """Decide the next agent in a dynamic run, or signal stop.

    This is a simple sequential cursor over a fixed order; subclass and
    override ``next_agent`` for adaptive logic.
    """

    order: List[str] = field(default_factory=list)
    _cursor: int = field(default=0, init=False, repr=False)

    def next_agent(self, state: AgentGraphState) -> str | None:
        """Return the next agent name, or ``None`` to stop."""
        if self._cursor >= len(self.order):
            return None
        name = self.order[self._cursor]
        self._cursor += 1
        return name

    def reset(self) -> None:
        """Reset the cursor to the beginning."""
        self._cursor = 0


__all__ = [
    "RunTypeRouter",
    "SupervisorPolicy",
]
