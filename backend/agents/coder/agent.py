"""Coder agent responsible for translating plans into code level actions."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent


class CoderAgent(LangChainAgent):
    """Outline concrete coding tasks derived from the architecture."""

    name = "coder"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Coder agent. Translate architectural guidance into "
                    "actionable implementation tasks for the engineering team.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "Recent plan:\n{plan}\n"
                    "Available artifacts:\n{artifacts}\n"
                    "List concrete coding tasks grouped by component.",
                ),
            ]
        )

    def prepare_inputs(self, context: AgentContext) -> dict[str, str]:
        inputs = super().prepare_inputs(context)
        plan_steps = context.artifacts.get("planner", {}).get("steps", [])
        inputs["plan"] = "\n".join(f"- {step}" for step in plan_steps) or "(no plan yet)"
        return inputs

    def fallback_result(self, context: AgentContext) -> AgentResult:
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
