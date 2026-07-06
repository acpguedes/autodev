"""Regex-based lexical symbol extractor.

Extracts top-level ``def`` and ``class`` definitions from source code using
stdlib regex — no external dependencies.
"""

from __future__ import annotations

import re

from backend.repository.providers.symbol_span import SymbolSpan

# Matches top-level (no leading whitespace) def/class definitions, capturing
# the keyword (def/class) and the symbol name.
_TOP_LEVEL_PATTERN = re.compile(r"^(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)

_KIND_BY_KEYWORD = {"def": "function", "class": "class"}


class LexicalProvider:
    """Extract symbols using plain regular expressions."""

    def extract_symbols(self, code: str, language: str) -> list[str]:  # noqa: ARG002
        """Return top-level function and class names found in *code*.

        The *language* parameter is accepted for interface compatibility but is
        ignored — the regex heuristic works for Python-like syntax only.
        """
        return [match.group(2) for match in _TOP_LEVEL_PATTERN.finditer(code)]

    def extract_symbol_spans(self, code: str, language: str) -> list[SymbolSpan]:  # noqa: ARG002
        """Return best-effort line spans for each top-level def/class in *code*.

        Used as :mod:`backend.repository.chunking`'s fallback symbol-span
        source when a tree-sitter grammar is unavailable. Each span runs from
        its ``def``/``class`` line to the line before the next top-level
        definition (or end of file) — an approximation, not a real parse.

        Args:
            code: Source code to extract spans from.
            language: Accepted for interface compatibility; ignored.

        Returns:
            Spans in source order; an empty list if *code* has no top-level
            definitions.
        """
        matches = list(_TOP_LEVEL_PATTERN.finditer(code))
        if not matches:
            return []
        total_lines = code.count("\n") + (0 if code.endswith("\n") or not code else 1)
        spans: list[SymbolSpan] = []
        for index, match in enumerate(matches):
            start_line = code.count("\n", 0, match.start())
            end_line = (
                code.count("\n", 0, matches[index + 1].start()) - 1
                if index + 1 < len(matches)
                else max(start_line, total_lines - 1)
            )
            end_byte = matches[index + 1].start() if index + 1 < len(matches) else len(code)
            spans.append(
                SymbolSpan(
                    name=match.group(2),
                    kind=_KIND_BY_KEYWORD[match.group(1)],
                    start_line=start_line,
                    end_line=max(start_line, end_line),
                    start_byte=len(code[: match.start()].encode("utf-8")),
                    end_byte=len(code[:end_byte].encode("utf-8")),
                )
            )
        return spans


__all__ = ["LexicalProvider"]
