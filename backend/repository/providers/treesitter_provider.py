"""Tree-sitter symbol extractor with a config-driven language registry (E7-S1).

Real tree-sitter parsing is implemented for Python via
:data:`_LANGUAGE_REGISTRY` below — the grammar package is already vendored
(``tree-sitter-python`` in ``backend/requirements.txt``). Adding another
language later is a one-line registry entry (loader + node-type vocabulary),
not a redesign; no other languages are wired in yet by design (scoped to
Python for E7-S1).

Degrades gracefully to :class:`LexicalProvider` when ``tree_sitter`` is not
installed, the requested language has no registry entry, or parsing itself
raises for any reason — a parse failure must never abort a caller's batch.
"""

from __future__ import annotations

from typing import Any, Callable

from backend.repository.providers.lexical_provider import LexicalProvider
from backend.repository.providers.symbol_span import SymbolSpan

try:
    import tree_sitter  # type: ignore[import-untyped]

    _TREE_SITTER_AVAILABLE = True
except ImportError:
    _TREE_SITTER_AVAILABLE = False


def _load_python_language() -> Any:
    """Build the tree-sitter ``Language`` for Python from the vendored grammar package.

    Returns:
        A ``tree_sitter.Language`` built from ``tree_sitter_python``.

    Raises:
        ImportError: If ``tree_sitter_python`` is not installed.
    """
    import tree_sitter_python  # type: ignore[import-untyped]

    return tree_sitter.Language(tree_sitter_python.language())


#: Registry mapping a language name to a zero-arg loader returning its
#: tree-sitter ``Language``. Add a new language by adding one entry here
#: (plus its grammar package to ``backend/requirements.txt`` and an entry in
#: ``_DEFINITION_NODE_TYPES``/``_IMPORT_NODE_TYPES`` below) — no other code
#: needs to change.
_LANGUAGE_REGISTRY: dict[str, Callable[[], Any]] = {
    "python": _load_python_language,
}

#: Node types treated as function/class definitions, per language, mapped to
#: the symbol ``kind`` recorded on their :class:`SymbolSpan`.
_DEFINITION_NODE_TYPES: dict[str, dict[str, str]] = {
    "python": {"function_definition": "function", "class_definition": "class"},
}

#: Node types treated as import statements, per language.
_IMPORT_NODE_TYPES: dict[str, set[str]] = {
    "python": {"import_statement", "import_from_statement"},
}


class TreeSitterProvider:
    """Extract symbols (and their spans) via tree-sitter; fall back to lexical."""

    def __init__(self) -> None:
        """Initialize the provider, lazily building a ``Parser`` per language on first use."""
        self._fallback = LexicalProvider()
        self._parsers: dict[str, Any] = {}
        self._available = _TREE_SITTER_AVAILABLE

    def extract_symbols(self, code: str, language: str) -> list[str]:
        """Return function/class/import symbol names found in *code*, in source order.

        Uses a real tree-sitter parse when *language* is registered and the
        `tree_sitter` package (plus the language's grammar package) are
        installed. Falls back to the regex-based :class:`LexicalProvider` for
        unregistered languages, when tree-sitter is unavailable, or if
        parsing raises for any reason — a parse failure never aborts
        extraction, it just degrades for that one input.

        Args:
            code: Source code to extract symbols from.
            language: Language identifier (e.g. ``"python"``).

        Returns:
            Symbol names in source order.
        """
        parser = self._get_parser(language)
        if parser is None:
            return self._fallback.extract_symbols(code, language)
        try:
            spans, imports = self._parse(parser, code, language)
        except Exception:
            return self._fallback.extract_symbols(code, language)
        return [span.name for span in spans] + imports

    def extract_symbol_spans(self, code: str, language: str) -> list[SymbolSpan]:
        """Return function/class definition spans found in *code*, in source order.

        Used by :mod:`backend.repository.chunking` for syntax-aware chunk
        boundaries. Only definitions (not imports) are returned as spans —
        imports are not meaningful chunk boundaries.

        Args:
            code: Source code to extract spans from.
            language: Language identifier (e.g. ``"python"``).

        Returns:
            Definition spans in source order; an empty list if tree-sitter is
            unavailable, *language* is unregistered, or parsing fails.
        """
        parser = self._get_parser(language)
        if parser is None:
            return []
        try:
            spans, _imports = self._parse(parser, code, language)
        except Exception:
            return []
        return spans

    def _parse(self, parser: Any, code: str, language: str) -> tuple[list[SymbolSpan], list[str]]:
        """Parse *code* once and collect both definition spans and import names.

        Args:
            parser: Cached tree-sitter ``Parser`` for *language*.
            code: Source code to parse.
            language: Language identifier, used to look up the node-type vocabulary.

        Returns:
            A ``(spans, import_names)`` pair, both in source order.
        """
        definition_kinds = _DEFINITION_NODE_TYPES.get(language, {})
        import_types = _IMPORT_NODE_TYPES.get(language, set())
        source_bytes = code.encode("utf-8")
        tree = parser.parse(source_bytes)
        spans: list[SymbolSpan] = []
        imports: list[str] = []
        self._walk(tree.root_node, definition_kinds, import_types, source_bytes, spans, imports)
        return spans, imports

    def _walk(
        self,
        node: Any,
        definition_kinds: dict[str, str],
        import_types: set[str],
        source_bytes: bytes,
        spans: list[SymbolSpan],
        imports: list[str],
    ) -> None:
        """Recursively visit *node*, appending definition spans and import names in place."""
        kind = definition_kinds.get(node.type)
        if kind is not None:
            name_node = node.child_by_field_name("name")
            name = (
                source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                if name_node is not None
                else ""
            )
            spans.append(
                SymbolSpan(
                    name=name,
                    kind=kind,
                    start_line=node.start_point[0],
                    end_line=node.end_point[0],
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                )
            )
        elif node.type in import_types:
            for child in node.children:
                if child.type in ("dotted_name", "identifier", "aliased_import"):
                    imports.append(
                        source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                    )
        for child in node.children:
            self._walk(child, definition_kinds, import_types, source_bytes, spans, imports)

    def _get_parser(self, language: str) -> Any | None:
        """Return a cached tree-sitter ``Parser`` for *language*, or ``None`` if unavailable."""
        if not self._available or language not in _LANGUAGE_REGISTRY:
            return None
        if language not in self._parsers:
            try:
                ts_language = _LANGUAGE_REGISTRY[language]()
                self._parsers[language] = tree_sitter.Parser(ts_language)
            except Exception:
                return None
        return self._parsers[language]


__all__ = ["TreeSitterProvider"]
