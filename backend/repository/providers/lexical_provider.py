"""Regex-based lexical symbol extractor.

Extracts top-level ``def`` and ``class`` definitions from source code using
stdlib regex — no external dependencies.
"""

from __future__ import annotations

import re

# Matches top-level (no leading whitespace) def/class definitions.
_TOP_LEVEL_PATTERN = re.compile(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)


class LexicalProvider:
    """Extract symbols using plain regular expressions."""

    def extract_symbols(self, code: str, language: str) -> list[str]:  # noqa: ARG002
        """Return top-level function and class names found in *code*.

        The *language* parameter is accepted for interface compatibility but is
        ignored — the regex heuristic works for Python-like syntax only.
        """
        return _TOP_LEVEL_PATTERN.findall(code)


__all__ = ["LexicalProvider"]
