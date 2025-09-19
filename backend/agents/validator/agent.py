"""Validator agent that defines verification routines."""

from __future__ import annotations

from backend.agents.base import AgentContext, AgentResult


class ValidatorAgent:
    """Summarise validation activities that guarantee quality."""

    name = "validator"

    def run(self, context: AgentContext) -> AgentResult:
        validation_steps = [
            "Run pytest for backend modules",
            "Execute frontend lint and type checks",
            "Perform security scanning before deployment",
        ]
        metadata = {"validation_steps": validation_steps}
        description = "\n".join(f"- {step}" for step in validation_steps)
        return AgentResult(content=f"Validation steps:\n{description}", metadata=metadata)


__all__ = ["ValidatorAgent"]
