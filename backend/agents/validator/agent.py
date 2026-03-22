"""Validator agent that defines verification routines."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts import ValidatorOutput


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

    def metadata_model(self):
        return ValidatorOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        validation_steps = [
            "Run pytest for backend modules",
            "Exercise the /agents/contracts endpoint through API tests",
            "Confirm fallback agents emit schema-valid metadata without a live model",
        ]
        metadata = {
            "validation_steps": validation_steps,
            "success_criteria": [
                "Every agent result metadata payload validates against its published contract",
                "The API can return JSON schemas for UI-driven rendering",
            ],
        }
        description = "\n".join(f"- {step}" for step in validation_steps)
        return AgentResult(content=f"Validation steps:\n{description}", metadata=metadata)


__all__ = ["ValidatorAgent"]
