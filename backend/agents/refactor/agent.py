"""Refactoring analysis agent."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts_ext import RefactorOutput


class RefactorAgent(LangChainAgent):
    """Identify code smells and propose targeted refactoring changes."""

    name = "refactor"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Refactor agent. Analyse the codebase context for "
                    "code smells, duplication, excessive complexity, and coupling. "
                    "Propose concrete, minimal refactoring changes.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "Current user request: {user_request}\n"
                    "Conversation so far:\n{history}\n"
                    "Prior agent outputs:\n{artifacts}\n"
                    "List refactoring targets, identified smells, and suggested changes.",
                ),
            ]
        )

    def metadata_model(self):
        return RefactorOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        targets = ["backend/agents/base.py", "backend/orchestrator/service.py"]
        smells = [
            "No active LLM — static fallback refactor review.",
            "Long method detected in orchestrator service.",
        ]
        suggested_changes = [
            "Extract agent-node builder into a dedicated class.",
            "Replace inline dicts with typed dataclasses where applicable.",
        ]
        content = (
            "Refactor analysis (fallback):\n"
            "Targets: " + ", ".join(targets) + "\n"
            "Smells:\n" + "\n".join(f"- {s}" for s in smells) + "\n"
            "Suggested changes:\n" + "\n".join(f"- {c}" for c in suggested_changes)
        )
        return AgentResult(
            content=content,
            metadata={
                "targets": targets,
                "smells": smells,
                "suggested_changes": suggested_changes,
            },
        )

    def build_metadata(
        self,
        context: AgentContext,
        fallback: AgentResult,
        generated_text: str,
    ) -> dict:
        return dict(fallback.metadata)


__all__ = ["RefactorAgent"]


try:
    from backend.agents.registry import register_agent as _register_agent
except ImportError:
    def _register_agent(name):  # type: ignore[misc]
        return lambda cls: cls

_register_agent("refactor")(RefactorAgent)
