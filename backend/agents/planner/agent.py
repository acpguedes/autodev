"""Implementation of the planner agent."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent


class PlannerAgent(LangChainAgent):
    """Convert a high-level goal into an ordered list of tasks."""

    name = "planner"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Planner agent. Break the user's objective into a "
                    "succinct, prioritised list of steps.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "Conversation so far:\n{history}\n"
                    "Draft a numbered plan with 3-5 steps that other agents can follow.",
                ),
            ]
        )

    def fallback_result(self, context: AgentContext) -> AgentResult:
        goal = context.goal or "Refine project requirements"
        steps = [
            f"Understand the request: {goal}",
            "Inspect repository state and identify relevant assets",
            "Draft implementation tasks for each component (backend, frontend, infra)",
            "Define validation strategy and acceptance criteria",
        ]
        description = "\n".join(f"- {step}" for step in steps)
        return AgentResult(content=f"Proposed plan:\n{description}", metadata={"steps": steps})

    def build_metadata(
        self,
        context: AgentContext,
        fallback: AgentResult,
        generated_text: str,
    ) -> dict[str, list[str]]:
        return {"steps": list(fallback.metadata.get("steps", []))}


__all__ = ["PlannerAgent"]
