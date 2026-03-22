"""Repository navigation agent."""

from __future__ import annotations

from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts import NavigatorOutput
from backend.repository import RepositoryIntelligenceService


class NavigatorAgent(LangChainAgent):
    """Provide a lightweight but structured map of the repository."""

    name = "navigator"

    def __init__(self, project_root: Path | None = None) -> None:
        self._service = RepositoryIntelligenceService(project_root=project_root)
        super().__init__()

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Navigator agent. Inspect the repository context and return "
                    "a concise repository map with the most relevant files for the task.",
                ),
                (
                    "human",
                    "Root path: {root}\n"
                    "User goal: {goal}\n"
                    "Current user request: {user_request}\n"
                    "Recent history:\n{history}\n"
                    "Top directories: {directories}\n"
                    "Candidate files: {candidate_files}\n"
                    "Inventory sample:\n{inventory_sample}\n"
                    "Summarise which files or areas other agents should inspect first.",
                ),
            ]
        )

    def prepare_inputs(self, context: AgentContext) -> dict[str, str]:
        inputs = super().prepare_inputs(context)
        repository_context = self._build_repository_context(context)
        inputs["root"] = repository_context.root
        inputs["directories"] = ", ".join(repository_context.top_directories) or "(none)"
        inputs["candidate_files"] = self._render_candidate_files(repository_context)
        inputs["inventory_sample"] = "\n".join(repository_context.inventory_sample) or "(empty)"
        return inputs

    def metadata_model(self):
        return NavigatorOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        repository_context = self._build_repository_context(context)
        candidate_paths = [item.path for item in repository_context.candidate_files]
        if candidate_paths:
            message = (
                "Repository context prepared. Prioritise these files: "
                + ", ".join(candidate_paths)
            )
        else:
            message = (
                "Repository context prepared. No strong file matches were found, "
                "so use the inventory sample as a starting point."
            )
        return AgentResult(content=message, metadata=repository_context.to_dict())

    def _build_repository_context(self, context: AgentContext):
        query = self._build_query(context)
        return self._service.build_context(query=query, limit=8)

    def _build_query(self, context: AgentContext) -> str:
        recent_user_messages = [
            entry.get("content", "")
            for entry in context.history
            if entry.get("role") == "user"
        ]
        return "\n".join(filter(None, [context.goal or "", *recent_user_messages]))

    def _render_candidate_files(self, repository_context) -> str:
        if not repository_context.candidate_files:
            return "(no direct matches)"
        return "\n".join(
            f"- {item.path} (score={item.score}; reasons={', '.join(item.reasons)})"
            for item in repository_context.candidate_files
        )


__all__ = ["NavigatorAgent"]
