"""DevOps agent describing automation requirements."""

from __future__ import annotations

from backend.agents.base import AgentContext, AgentResult


class DevOpsAgent:
    """Outline CI/CD and runtime automation needs."""

    name = "devops"

    def run(self, context: AgentContext) -> AgentResult:
        deliverables = {
            "docker": "Create Python 3.11 image exposing the FastAPI app",
            "ci": "Configure GitHub Actions workflow running tests and lint",
            "infrastructure": "Prepare Terraform placeholder for future cloud resources",
        }
        description = "\n".join(f"- {key}: {value}" for key, value in deliverables.items())
        return AgentResult(content=f"DevOps tasks:\n{description}", metadata=deliverables)


__all__ = ["DevOpsAgent"]
