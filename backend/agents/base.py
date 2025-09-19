"""Core abstractions shared by all AutoDev agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Protocol


@dataclass(slots=True)
class AgentContext:
    """Lightweight container with execution context for an agent."""

    session_id: str
    goal: str | None = None
    history: List[Dict[str, str]] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)

    def with_artifact(self, key: str, value: Any) -> "AgentContext":
        """Return a new context that includes an extra artifact."""

        updated = dict(self.artifacts)
        updated[key] = value
        return AgentContext(
            session_id=self.session_id,
            goal=self.goal,
            history=list(self.history),
            artifacts=updated,
        )


@dataclass(slots=True)
class AgentResult:
    """Output produced by an agent execution."""

    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    """Protocol implemented by all concrete agents."""

    name: str

    def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent with the provided context."""


__all__ = ["Agent", "AgentContext", "AgentResult"]
