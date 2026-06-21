"""Documentation generation agent."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts_ext import DocsOutput


class DocsAgent(LangChainAgent):
    """Generate or update documentation for the project."""

    name = "docs"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Docs agent. Produce clear, accurate documentation "
                    "for the requested changes — including module docstrings, ADRs, "
                    "README updates, and API reference stubs.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "Current user request: {user_request}\n"
                    "Conversation so far:\n{history}\n"
                    "Prior agent outputs:\n{artifacts}\n"
                    "List the documents to create/update, the sections to include, "
                    "and provide a concise summary of documentation changes.",
                ),
            ]
        )

    def metadata_model(self):
        return DocsOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        documents = ["README.md", "docs/architecture/overview.md"]
        sections = ["Overview", "Setup", "Architecture", "API Reference"]
        summary = (
            "No active LLM — static fallback documentation outline generated. "
            "Update README and architecture docs with the latest changes."
        )
        content = (
            "Documentation plan (fallback):\n"
            "Documents: " + ", ".join(documents) + "\n"
            "Sections: " + ", ".join(sections) + "\n"
            "Summary: " + summary
        )
        return AgentResult(
            content=content,
            metadata={
                "documents": documents,
                "sections": sections,
                "summary": summary,
            },
        )

    def build_metadata(
        self,
        context: AgentContext,
        fallback: AgentResult,
        generated_text: str,
    ) -> dict:
        return dict(fallback.metadata)


__all__ = ["DocsAgent"]


try:
    from backend.agents.registry import register_agent as _register_agent
except ImportError:
    def _register_agent(name):  # type: ignore[misc]
        return lambda cls: cls

_register_agent("docs")(DocsAgent)
