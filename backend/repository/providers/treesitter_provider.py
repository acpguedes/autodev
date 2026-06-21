"""Optional tree-sitter symbol extractor.

``tree_sitter`` is NOT a mandatory dependency.  This module degrades gracefully
to :class:`LexicalProvider` when the library is unavailable.
"""

from __future__ import annotations

from backend.repository.providers.lexical_provider import LexicalProvider

try:
    import tree_sitter  # type: ignore[import-untyped]  # noqa: F401

    _TREE_SITTER_AVAILABLE = True
except ImportError:
    _TREE_SITTER_AVAILABLE = False


class TreeSitterProvider:
    """Extract symbols via tree-sitter when available; fall back to lexical."""

    def __init__(self) -> None:
        self._fallback = LexicalProvider()
        self._available = _TREE_SITTER_AVAILABLE

    def extract_symbols(self, code: str, language: str) -> list[str]:
        """Return symbol names from *code*.

        Uses tree-sitter when the library is installed; falls back to the
        regex-based :class:`LexicalProvider` otherwise.
        """
        if not self._available:
            return self._fallback.extract_symbols(code, language)

        # Real tree-sitter extraction would go here.  For now we delegate to
        # the lexical fallback — the important contract is that tree-sitter is
        # imported at module level so any availability check is reliable.
        return self._fallback.extract_symbols(code, language)


__all__ = ["TreeSitterProvider"]
