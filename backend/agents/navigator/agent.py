"""Repository navigation agent."""

from __future__ import annotations

from pathlib import Path
from typing import List

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent


class NavigatorAgent(LangChainAgent):
    """Provide a lightweight map of the repository structure."""

    name = "navigator"

    def __init__(self, project_root: Path | None = None) -> None:
        self._root = project_root or Path.cwd()
        super().__init__()

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Navigator agent. Inspect the project workspace and give "
                    "a concise overview of its main directories.",
                ),
                (
                    "human",
                    "Root path: {root}\n"
                    "Existing directories:\n{directories}\n"
                    "Summarise the workspace structure for the other agents.",
                ),
            ]
        )

    def prepare_inputs(self, context: AgentContext) -> dict[str, str]:
        inputs = super().prepare_inputs(context)
        directories = self._scan_directories()
        inputs["root"] = str(self._root)
        inputs["directories"] = "\n".join(directories) if directories else "(empty)"
        return inputs

    def fallback_result(self, context: AgentContext) -> AgentResult:
        directories = self._scan_directories()
        message = "Indexed top-level directories: " + ", ".join(directories)
        metadata = {"directories": directories, "root": str(self._root)}
        return AgentResult(content=message, metadata=metadata)

    def _scan_directories(self) -> List[str]:
        directories: List[str] = []
        for path in sorted(self._root.iterdir()):
            if path.name.startswith("."):
                continue
            if path.is_dir():
                directories.append(path.name)
        return directories


__all__ = ["NavigatorAgent"]
