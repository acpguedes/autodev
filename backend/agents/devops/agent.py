"""DevOps agent describing automation requirements."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts import DevOpsOutput


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
                    "Current user request: {user_request}\n"
                    "Context:\n{history}\n"
                    "Artifacts:\n{artifacts}\n"
                    "List the core DevOps deliverables with short explanations.",
                ),
            ]
        )

    def metadata_model(self):
        return DevOpsOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        deliverables = {
            "docker": "Keep the FastAPI service runnable in the existing self-hosted container workflow",
            "ci": "Run backend tests that verify structured-output contracts remain stable",
            "configuration": "Preserve the local file-based runtime config path for OSS deployments",
        }
        metadata = {
            "deliverables": deliverables,
            "operational_checks": [
                "Verify the API exposes agent contract schemas",
                "Ensure deterministic fallback agents still emit valid metadata",
            ],
        }
        description = "\n".join(f"- {key}: {value}" for key, value in deliverables.items())
        return AgentResult(content=f"DevOps tasks:\n{description}", metadata=metadata)


__all__ = ["DevOpsAgent"]
