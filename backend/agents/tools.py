"""Least-privilege tool and skill broker for agent execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.agents.manifest import AgentManifest


class ToolAccessDenied(PermissionError):
    """Raised when an agent attempts to use a tool, skill, or network access it was not granted."""


class AgentToolBroker:
    """Grants an agent access only to the tools, skills, and network scope in its manifest."""

    def __init__(
        self,
        manifest: AgentManifest,
        *,
        tools: dict[str, Callable[..., Any]] | None = None,
        skills: dict[str, Callable[..., Any]] | None = None,
        skill_broker: Any | None = None,
    ) -> None:
        """Initialize the broker for a single agent manifest.

        Args:
            manifest: Manifest describing the agent's granted permissions.
            tools: Mapping of tool id to callable implementation, if any.
            skills: Mapping of skill id to callable implementation, if any.
            skill_broker: Optional :class:`backend.skills.invoker.SkillInvocationBroker`
                resolving skills through the durable Skill Registry. When set,
                it takes precedence over ``skills`` for granted skill calls.
        """
        self._manifest = manifest
        self._tools = tools or {}
        self._skills = skills or {}
        self._skill_broker = skill_broker
        self._allowed_tools = {item.id for item in manifest.permissions.tools}
        self._allowed_skills = {item.id for item in manifest.permissions.skills}

    def call_tool(self, tool_id: str, **kwargs: Any) -> Any:
        """Invoke a registered tool on behalf of the agent.

        Args:
            tool_id: Identifier of the tool to call.
            **kwargs: Keyword arguments forwarded to the tool implementation.

        Returns:
            The tool's return value.

        Raises:
            ToolAccessDenied: If the tool is not granted to the agent or not registered.
        """
        if tool_id not in self._allowed_tools:
            raise ToolAccessDenied(f"tool {tool_id!r} is not granted to {self._manifest.id}")
        if tool_id not in self._tools:
            raise ToolAccessDenied(f"tool {tool_id!r} is not registered")
        return self._tools[tool_id](**kwargs)

    def call_skill(self, skill_id: str, **kwargs: Any) -> Any:
        """Invoke a registered skill on behalf of the agent.

        Args:
            skill_id: Identifier of the skill to call.
            **kwargs: Keyword arguments forwarded to the skill implementation.

        Returns:
            The skill's return value.

        Raises:
            ToolAccessDenied: If the skill is not granted to the agent or not registered.
        """
        if skill_id not in self._allowed_skills:
            raise ToolAccessDenied(f"skill {skill_id!r} is not granted to {self._manifest.id}")
        if self._skill_broker is not None:
            return self._skill_broker.invoke(skill_id, **kwargs)
        if skill_id not in self._skills:
            raise ToolAccessDenied(f"skill {skill_id!r} is not registered")
        return self._skills[skill_id](**kwargs)

    def open_network(self, host: str, port: int) -> tuple[str, int]:
        """Validate and return a network endpoint the agent is permitted to reach.

        Args:
            host: Target hostname.
            port: Target port.

        Returns:
            The ``(host, port)`` tuple, unchanged, if network access is permitted.

        Raises:
            ToolAccessDenied: If the agent's manifest denies network access.
        """
        if self._manifest.permissions.network == "none":
            raise ToolAccessDenied(f"network is denied by default for {self._manifest.id}")
        return host, port


__all__ = ["AgentToolBroker", "ToolAccessDenied"]
