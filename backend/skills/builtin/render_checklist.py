"""Built-in skill: render_checklist.

Render a list of items as a GitHub-flavoured Markdown checklist.
"""

from __future__ import annotations

from typing import Any

from backend.skills.base import BaseSkill, SkillContext, SkillResult
from backend.skills.registry import register_skill


@register_skill("render_checklist", description="Render a list of items as a Markdown checklist.")
class RenderChecklistSkill(BaseSkill):
    """Convert a list of items into a markdown checkbox list."""

    name = "render_checklist"
    description = "Render a list of items as a Markdown checklist."

    def run(self, context: SkillContext) -> SkillResult:
        items: list[Any] = context.inputs.get("items", [])

        lines = [f"- [ ] {item}" for item in items]
        content = "\n".join(lines) if lines else "(empty checklist)"

        return SkillResult(
            content=content,
            data={"item_count": len(items), "items": [str(i) for i in items]},
            success=True,
        )
