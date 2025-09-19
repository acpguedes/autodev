"""Coder agent responsible for translating plans into code level actions."""

from __future__ import annotations

from backend.agents.base import AgentContext, AgentResult


class CoderAgent:
    """Outline concrete coding tasks derived from the architecture."""

    name = "coder"

    def run(self, context: AgentContext) -> AgentResult:
        plan_steps = context.artifacts.get("planner", {}).get("steps", [])
        coding_tasks = [
            "Implement FastAPI orchestrator endpoints",
            "Create shared agent abstractions and stubs",
            "Develop chat UI components in Next.js",
            "Author automated tests for orchestrator logic",
        ]
        metadata = {"plan_steps": plan_steps, "coding_tasks": coding_tasks}
        description = "\n".join(f"- {task}" for task in coding_tasks)
        return AgentResult(content=f"Coding tasks:\n{description}", metadata=metadata)


__all__ = ["CoderAgent"]
