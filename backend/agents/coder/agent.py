"""Coder agent responsible for translating plans into code level actions."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts import CoderOutput


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
                    "Current user request: {user_request}\n"
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

    def metadata_model(self):
        return CoderOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        coding_tasks = [
            {"component": "backend/api", "task": "Expose agent contract schemas through a typed API endpoint"},
            {"component": "backend/agents", "task": "Validate agent metadata against Pydantic contracts"},
            {"component": "tests/backend", "task": "Cover schema publishing and metadata validation behavior"},
            {"component": "docs", "task": "Document the structured-output slice and roadmap progress"},
        ]
        metadata = {
            "coding_tasks": coding_tasks,
            "test_updates": [
                "Add orchestrator coverage for contract exposure",
                "Assert API returns the expected schema documents",
            ],
            "touched_components": [
                "backend/api",
                "backend/agents",
                "tests/backend",
                "docs",
            ],
        }
        description = "\n".join(f"- {item['component']}: {item['task']}" for item in coding_tasks)
        return AgentResult(content=f"Coding tasks:\n{description}", metadata=metadata)


__all__ = ["CoderAgent"]
