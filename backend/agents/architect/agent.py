"""Architect agent that designs high-level components."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts import ArchitectOutput


class ArchitectAgent(LangChainAgent):
    """Create a structured architecture proposal for downstream agents."""

    name = "architect"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Architect agent. Transform the planner output and other "
                    "artifacts into a coherent architecture proposal covering backend, "
                    "frontend and infrastructure considerations.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "Current user request: {user_request}\n"
                    "Plan steps:\n{plan}\n"
                    "Known artifacts:\n{artifacts}\n"
                    "Describe the architecture with concise bullets for each domain.",
                ),
            ]
        )

    def prepare_inputs(self, context: AgentContext) -> dict[str, str]:
        inputs = super().prepare_inputs(context)
        plan_steps = context.artifacts.get("planner", {}).get("steps", [])
        inputs["plan"] = "\n".join(f"- {step}" for step in plan_steps) or "(no plan yet)"
        return inputs

    def metadata_model(self):
        return ArchitectOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        architecture = {
            "backend": {
                "summary": "Keep workflow coordination and API contracts in the FastAPI control plane.",
                "decisions": [
                    "Persist orchestrator state outside prompt text",
                    "Validate agent metadata before sharing it downstream",
                ],
            },
            "frontend": {
                "summary": "Render agent results from typed contracts instead of ad-hoc metadata.",
                "decisions": [
                    "Use published JSON schemas to drive future UI components",
                ],
            },
            "infrastructure": {
                "summary": "Preserve the self-hostable bootstrap path while contracts mature.",
                "decisions": [
                    "Keep the current file-backed configuration and SQLite bootstrap store",
                    "Prepare the API surface for later PostgreSQL and Redis upgrades",
                ],
            },
        }
        description = "; ".join(
            f"{section}: {details['summary']}" for section, details in architecture.items()
        )
        return AgentResult(content=f"Architecture proposal -> {description}", metadata=architecture)


__all__ = ["ArchitectAgent"]
