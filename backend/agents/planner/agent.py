"""Implementation of the planner agent."""

from __future__ import annotations

from backend.agents.base import AgentContext, AgentResult


class PlannerAgent:
    """Convert a high-level goal into an ordered list of tasks."""

    name = "planner"

    def run(self, context: AgentContext) -> AgentResult:
        goal = context.goal or "Refine project requirements"
        steps = [
            f"Understand the request: {goal}",
            "Inspect repository state and identify relevant assets",
            "Draft implementation tasks for each component (backend, frontend, infra)",
            "Define validation strategy and acceptance criteria",
        ]
        description = "\n".join(f"- {step}" for step in steps)
        return AgentResult(content=f"Proposed plan:\n{description}", metadata={"steps": steps})


__all__ = ["PlannerAgent"]
