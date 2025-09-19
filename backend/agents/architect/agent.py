"""Architect agent that designs high-level components."""

from __future__ import annotations

from backend.agents.base import AgentContext, AgentResult


class ArchitectAgent:
    """Create a structured architecture proposal for downstream agents."""

    name = "architect"

    def run(self, context: AgentContext) -> AgentResult:
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
