"""Shared span type for syntax-aware chunking (E7-S1-T2).

Both :class:`~backend.repository.providers.treesitter_provider.TreeSitterProvider`
and :class:`~backend.repository.providers.lexical_provider.LexicalProvider` can
optionally implement ``extract_symbol_spans(code, language) -> list[SymbolSpan]``
— a superset of the required ``extract_symbols`` — so
:mod:`backend.repository.chunking` can split source at real symbol boundaries
regardless of which provider is active.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SymbolSpan:
    """A named symbol's line/byte span within a source file.

    Attributes:
        name: Symbol name (function/class identifier).
        kind: Symbol kind, e.g. ``"function"`` or ``"class"``.
        start_line: 0-based inclusive start line.
        end_line: 0-based inclusive end line.
        start_byte: Inclusive start byte offset in the source's UTF-8 encoding.
        end_byte: Exclusive end byte offset in the source's UTF-8 encoding.
    """

    name: str
    kind: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int


__all__ = ["SymbolSpan"]
