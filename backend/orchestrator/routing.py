"""Dynamic routing and supervisor policy for the orchestrator.

``RunTypeRouter`` is the default per-run agent-order policy of the chat path
(E63-S4); ``SupervisorPolicy`` remains standalone.

Key exports:
- ``RunTypeRouter`` — maps each ``RunType`` to an ordered list of agent names.
- ``SupervisorPolicy`` — stateful supervisor deciding the next agent or stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
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

_ARCHITECTURAL_WORDS = {"architecture", "architect", "design", "redesign", "refactor", "restructure"}

_ROUTE_MAP: dict[RunType, List[str]] = {
    RunType.DOCUMENTATION_UPDATE: ["navigator", "analyzer", "responder"],
    RunType.VALIDATION_ONLY: ["navigator", "validator", "responder"],
    RunType.DEVOPS_CHANGE: ["navigator", "analyzer", "devops", "responder"],
    RunType.GREENFIELD_BOOTSTRAP: _FULL_ORDER,
    # A change in an existing project does not re-open design decisions.
    RunType.EXISTING_REPO_CHANGE: [
        "navigator",
        "analyzer",
        "coder",
        "devops",
        "validator",
        "responder",
    ],
    RunType.PLAN_EXECUTION: _FULL_ORDER,
}


class RunTypeRouter:
    """Maps each ``RunType`` to an ordered list of agent names."""

    def __init__(self, route_map: dict[RunType, List[str]] | None = None) -> None:
        self._map: dict[RunType, List[str]] = (
            dict(route_map) if route_map is not None else dict(_ROUTE_MAP)
        )

    def order_for(self, run_type: RunType, intent: str = "") -> List[str]:
        """Return the agent execution order for *run_type*.

        Falls back to the full linear order for unmapped types. When *intent*
        states an architectural task, ``architect`` is restored after
        ``analyzer`` -- the change is "not always", not "never".

        Args:
            run_type: The inferred run type.
            intent: Goal/message text, used only to detect architectural work.

        Returns:
            Ordered agent names.
        """
        order = list(self._map.get(run_type, _FULL_ORDER))
        words = set(re.findall(r"[a-z0-9]+", intent.lower()))
        if run_type == RunType.EXISTING_REPO_CHANGE and "architect" not in order and words & _ARCHITECTURAL_WORDS:
            anchor = order.index("analyzer") + 1 if "analyzer" in order else 0
            order.insert(anchor, "architect")
        return order

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
