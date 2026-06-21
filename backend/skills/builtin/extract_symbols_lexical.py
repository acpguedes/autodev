"""Built-in skill: extract_symbols_lexical.

Extract top-level ``def`` and ``class`` names from source code via regex.
Deterministic, stdlib only, no tree-sitter required.
"""

from __future__ import annotations

import re

from backend.skills.base import BaseSkill, SkillContext, SkillResult
from backend.skills.registry import register_skill

# Matches Python-style top-level definitions at column 0.
_PYTHON_TOP_LEVEL = re.compile(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)

# Generic fallback: any line that looks like a function/class declaration.
_GENERIC_TOP_LEVEL = re.compile(
    r"^(?:def|class|function|func|fn|sub|proc)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)


@register_skill(
    "extract_symbols_lexical",
    description="Extract top-level def/class names from source code using regex (no tree-sitter).",
)
class ExtractSymbolsLexicalSkill(BaseSkill):
    """Return a sorted list of top-level symbol names found in source code."""

    name = "extract_symbols_lexical"
    description = "Extract top-level def/class names from source code using regex (no tree-sitter)."

    def run(self, context: SkillContext) -> SkillResult:
        code: str = context.inputs.get("code", "")
        language: str = context.inputs.get("language", "python").lower()

        if language in ("python", "py"):
            pattern = _PYTHON_TOP_LEVEL
        else:
            pattern = _GENERIC_TOP_LEVEL

        symbols = pattern.findall(code)
        # Preserve order but deduplicate while keeping first occurrence.
        seen: set[str] = set()
        unique: list[str] = []
        for sym in symbols:
            if sym not in seen:
                seen.add(sym)
                unique.append(sym)

        content = ", ".join(unique) if unique else "(no symbols found)"
        return SkillResult(
            content=content,
            data={"symbols": unique, "language": language},
            success=True,
        )
