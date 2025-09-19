"""DevOps agent describing automation requirements."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent


class DevOpsAgent(LangChainAgent):
    """Outline CI/CD and runtime automation needs."""

    name = "devops"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the DevOps agent. Summarise the automation and infrastructure "
                    "work necessary to support the project roadmap.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "Context:\n{history}\n"
                    "Artifacts:\n{artifacts}\n"
                    "List the core DevOps deliverables with short explanations.",
                ),
            ]
        )

    def fallback_result(self, context: AgentContext) -> AgentResult:
        deliverables = {
            "docker": "Create Python 3.11 image exposing the FastAPI app",
            "ci": "Configure GitHub Actions workflow running tests and lint",
            "infrastructure": "Prepare Terraform placeholder for future cloud resources",
        }
        description = "\n".join(f"- {key}: {value}" for key, value in deliverables.items())
        return AgentResult(content=f"DevOps tasks:\n{description}", metadata=deliverables)


__all__ = ["DevOpsAgent"]
