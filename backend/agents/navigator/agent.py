"""Repository navigation agent."""

from __future__ import annotations

from pathlib import Path
from typing import List

from backend.agents.base import AgentContext, AgentResult


class NavigatorAgent:
    """Provide a lightweight map of the repository structure."""

    name = "navigator"

    def __init__(self, project_root: Path | None = None) -> None:
        self._root = project_root or Path.cwd()

    def run(self, context: AgentContext) -> AgentResult:
        directories: List[str] = []
        for path in sorted(self._root.iterdir()):
            if path.name.startswith("."):
                continue
            if path.is_dir():
                directories.append(path.name)

        message = "Indexed top-level directories: " + ", ".join(directories)
        metadata = {"directories": directories, "root": str(self._root)}
        return AgentResult(content=message, metadata=metadata)


__all__ = ["NavigatorAgent"]
