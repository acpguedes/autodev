"""Skills subsystem for AutoDev Architect.

A *skill* is a lightweight, deterministic, reusable capability — no LLM or
LangChain dependency required.  Skills are defined by implementing the
:class:`Skill` structural protocol (or subclassing :class:`BaseSkill`) and
registering via :func:`register_skill`.

Quick start::

    from backend.skills import register_skill, SkillContext, SkillResult

    @register_skill("greet")
    class GreetSkill:
        name = "greet"
        description = "Return a greeting."

        def run(self, context: SkillContext) -> SkillResult:
            name = context.inputs.get("name", "World")
            return SkillResult(content=f"Hello, {name}!")

Discovery::

    from backend.skills import discover_skills
    skills = discover_skills()   # also imports built-ins

Invocation::

    from backend.skills import invoke_skill, SkillContext
    result = invoke_skill("greet", SkillContext(inputs={"name": "Alice"}))
"""

from backend.skills.base import BaseSkill, Skill, SkillContext, SkillResult
from backend.skills.registry import (
    discover_skills,
    get_registry,
    invoke_skill,
    register_skill,
)

__all__ = [
    "Skill",
    "SkillContext",
    "SkillResult",
    "BaseSkill",
    "register_skill",
    "get_registry",
    "discover_skills",
    "invoke_skill",
]
