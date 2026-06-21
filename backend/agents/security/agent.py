"""Security reviewer agent."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts_ext import SecurityOutput


class SecurityAgent(LangChainAgent):
    """Review code and architecture changes for security concerns."""

    name = "security"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Security agent. Review changes, architecture decisions, "
                    "and requirements for security risks such as injection, authentication "
                    "flaws, insecure data exposure, and dependency vulnerabilities.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "Current user request: {user_request}\n"
                    "Conversation so far:\n{history}\n"
                    "Prior agent outputs:\n{artifacts}\n"
                    "Identify security findings, assign a severity (info/low/medium/high/critical), "
                    "and list concrete recommendations.",
                ),
            ]
        )

    def metadata_model(self):
        return SecurityOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        findings = [
            "No active LLM configured — static fallback security review.",
            "Review authentication and authorisation boundaries.",
            "Validate all external inputs and sanitise before persistence.",
        ]
        recommendations = [
            "Enable dependency vulnerability scanning (e.g. pip-audit, Trivy).",
            "Enforce least-privilege access on all service accounts.",
        ]
        content = (
            "Security review (fallback):\n"
            + "\n".join(f"- {f}" for f in findings)
            + "\n\nRecommendations:\n"
            + "\n".join(f"- {r}" for r in recommendations)
        )
        return AgentResult(
            content=content,
            metadata={
                "findings": findings,
                "severity": "info",
                "recommendations": recommendations,
            },
        )

    def build_metadata(
        self,
        context: AgentContext,
        fallback: AgentResult,
        generated_text: str,
    ) -> dict:
        return dict(fallback.metadata)


__all__ = ["SecurityAgent"]


# Self-registration — guarded so this module can be imported independently
# even before backend.agents.registry exists (e.g. during early development).
try:
    from backend.agents.registry import register_agent as _register_agent
except ImportError:
    def _register_agent(name):  # type: ignore[misc]
        return lambda cls: cls

_register_agent("security")(SecurityAgent)
