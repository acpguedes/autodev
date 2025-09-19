"""Architect agent that designs high-level components."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent


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

    def fallback_result(self, context: AgentContext) -> AgentResult:
        architecture = {
            "backend": {
                "framework": "FastAPI",
                "modules": ["orchestrator", "agents", "api"],
            },
            "frontend": {
                "framework": "Next.js",
                "features": ["chat", "plan viewer", "diff inspector"],
            },
            "infrastructure": {
                "docker": True,
                "ci": "GitHub Actions",
            },
        }
        description = "; ".join(
            f"{section}: {details}" for section, details in architecture.items()
        )
        return AgentResult(content=f"Architecture proposal -> {description}", metadata=architecture)


__all__ = ["ArchitectAgent"]
