"""Validator agent that defines verification routines."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent


class ValidatorAgent(LangChainAgent):
    """Summarise validation activities that guarantee quality."""

    name = "validator"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Validator agent. Outline the testing and verification work "
                    "required to ensure the deliverables are production ready.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "Recent discussion:\n{history}\n"
                    "Artifacts:\n{artifacts}\n"
                    "List concrete validation steps.",
                ),
            ]
        )

    def fallback_result(self, context: AgentContext) -> AgentResult:
        validation_steps = [
            "Run pytest for backend modules",
            "Execute frontend lint and type checks",
            "Perform security scanning before deployment",
        ]
        metadata = {"validation_steps": validation_steps}
        description = "\n".join(f"- {step}" for step in validation_steps)
        return AgentResult(content=f"Validation steps:\n{description}", metadata=metadata)


__all__ = ["ValidatorAgent"]
