"""Core abstractions for the AutoDev skills subsystem.

A *Skill* is a lightweight, deterministic, reusable capability that can be
invoked by an agent, an API endpoint, or a CLI command.  Skills are
intentionally decoupled from agents: they have no LangChain dependency and
require no LLM.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SkillContext:
    """Execution context passed to every skill invocation."""

    inputs: Dict[str, Any] = field(default_factory=dict)
    project_root: Optional[str] = None


@dataclass
class SkillResult:
    """Output produced by a skill execution."""

    content: str
    data: Dict[str, Any] = field(default_factory=dict)
    success: bool = True


class Skill:
    """Structural protocol implemented by all concrete skill classes.

    Any class that defines ``name``, ``description``, and
    ``run(context) -> SkillResult`` satisfies this interface even without
    explicit inheritance.
    """

    name: str
    description: str

    def run(self, context: SkillContext) -> SkillResult:
        """Execute the skill and return a :class:`SkillResult`."""
        raise NotImplementedError


class BaseSkill(ABC):
    """Convenience base class for skills.

    Subclasses should:
    * set ``name`` and ``description`` as class-level strings;
    * implement :meth:`run`.

    Inheriting from :class:`BaseSkill` is optional; any class that satisfies
    the :class:`Skill` structural interface will work.
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, context: SkillContext) -> SkillResult:
        """Execute the skill and return a result."""


__all__ = ["SkillContext", "SkillResult", "Skill", "BaseSkill"]
