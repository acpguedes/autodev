"""Least-privilege tool and skill broker for agent execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.agents.manifest import AgentManifest


class ToolAccessDenied(PermissionError):
    pass


class AgentToolBroker:
    def __init__(
        self,
        manifest: AgentManifest,
        *,
        tools: dict[str, Callable[..., Any]] | None = None,
        skills: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        self._manifest = manifest
        self._tools = tools or {}
        self._skills = skills or {}
        self._allowed_tools = {item.id for item in manifest.permissions.tools}
        self._allowed_skills = {item.id for item in manifest.permissions.skills}

    def call_tool(self, tool_id: str, **kwargs: Any) -> Any:
        if tool_id not in self._allowed_tools:
            raise ToolAccessDenied(f"tool {tool_id!r} is not granted to {self._manifest.id}")
        if tool_id not in self._tools:
            raise ToolAccessDenied(f"tool {tool_id!r} is not registered")
        return self._tools[tool_id](**kwargs)

    def call_skill(self, skill_id: str, **kwargs: Any) -> Any:
        if skill_id not in self._allowed_skills:
            raise ToolAccessDenied(f"skill {skill_id!r} is not granted to {self._manifest.id}")
        if skill_id not in self._skills:
            raise ToolAccessDenied(f"skill {skill_id!r} is not registered")
        return self._skills[skill_id](**kwargs)

    def open_network(self, host: str, port: int) -> tuple[str, int]:
        if self._manifest.permissions.network == "none":
            raise ToolAccessDenied(f"network is denied by default for {self._manifest.id}")
        return host, port


__all__ = ["AgentToolBroker", "ToolAccessDenied"]
