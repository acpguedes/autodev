"""Built-in skill: summarize_diff.

Given a unified diff text, count added/removed lines and changed files
deterministically using stdlib only.
"""

from __future__ import annotations

from backend.skills.base import BaseSkill, SkillContext, SkillResult
from backend.skills.registry import register_skill


@register_skill("summarize_diff", description="Summarize a unified diff: count added/removed lines and changed files.")
class SummarizeDiffSkill(BaseSkill):
    """Parse a unified diff and return line/file change counts."""

    name = "summarize_diff"
    description = "Summarize a unified diff: count added/removed lines and changed files."

    def run(self, context: SkillContext) -> SkillResult:
        diff: str = context.inputs.get("diff", "")

        added = 0
        removed = 0
        changed_files: set[str] = set()
        current_file: str | None = None

        for line in diff.splitlines():
            if line.startswith("--- ") or line.startswith("+++ "):
                # e.g. "+++ b/path/to/file.py"
                parts = line.split(None, 1)
                if len(parts) == 2:
                    path = parts[1]
                    # Strip git a/ b/ prefixes
                    for prefix in ("a/", "b/"):
                        if path.startswith(prefix):
                            path = path[len(prefix):]
                            break
                    if path != "/dev/null":
                        current_file = path
                        changed_files.add(path)
                continue

            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1

        summary = (
            f"Changed files: {len(changed_files)}, "
            f"lines added: {added}, "
            f"lines removed: {removed}."
        )

        return SkillResult(
            content=summary,
            data={
                "added_lines": added,
                "removed_lines": removed,
                "changed_files": sorted(changed_files),
                "changed_file_count": len(changed_files),
            },
            success=True,
        )
