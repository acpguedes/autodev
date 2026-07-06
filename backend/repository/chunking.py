"""Syntax-aware chunking (E7-S1-T2).

Splits source code into chunks at symbol (function/class) boundaries, with a
configurable line-based overlap between adjacent chunks so a snippet near a
boundary keeps some surrounding context. Falls back to a single whole-file
chunk when the active provider cannot supply symbol spans (see
:class:`~backend.repository.providers.symbol_span.SymbolSpan`) or the file
has none (e.g. a script with no top-level functions/classes).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from backend.repository.providers import RepositoryProvider
from backend.repository.providers.symbol_span import SymbolSpan
from backend.repository.providers.treesitter_provider import TreeSitterProvider

#: Default number of trailing/leading context lines shared between adjacent chunks.
DEFAULT_OVERLAP_LINES = 2

#: Default span source: always attempts a real tree-sitter parse, degrading
#: internally to the lexical fallback when the package/grammar is
#: unavailable. Deliberately independent of ``get_provider()``'s
#: ``AUTODEV_REPO_PROVIDER`` env toggle (that gate controls the separate
#: ``/repository/symbols`` API; indexing should always prefer real parsing).
_DEFAULT_PROVIDER = TreeSitterProvider()


@dataclass(frozen=True, slots=True)
class Chunk:
    """A syntax-aware slice of a source file, ready for embedding/indexing.

    Attributes:
        file_path: Path of the source file this chunk was extracted from.
        symbol: Name of the enclosing function/class, or ``""`` for a
            whole-file chunk with no single enclosing symbol.
        start_line: 0-based inclusive start line (after overlap is applied).
        end_line: 0-based inclusive end line (after overlap is applied).
        content: The chunk's exact source text, including any overlap.
        content_hash: SHA-256 hex digest of ``content``, used to detect
            unchanged chunks across reindex runs.
    """

    file_path: str
    symbol: str
    start_line: int
    end_line: int
    content: str
    content_hash: str


def chunk_source(
    file_path: str,
    code: str,
    language: str = "python",
    *,
    overlap_lines: int = DEFAULT_OVERLAP_LINES,
    provider: RepositoryProvider | None = None,
) -> list[Chunk]:
    """Split *code* into syntax-aware chunks at symbol boundaries.

    Args:
        file_path: Path of the file *code* was read from; recorded on each chunk.
        code: Full source text to chunk.
        language: Language identifier passed to the provider.
        overlap_lines: Number of trailing/leading context lines shared between
            adjacent chunks.
        provider: Provider to extract symbol spans from; defaults to a
            shared :class:`TreeSitterProvider` instance.

    Returns:
        Chunks in source order. Falls back to a single whole-file chunk when
        the provider cannot supply symbol spans, or the file has none.
    """
    if not code:
        return []
    active_provider = provider or _DEFAULT_PROVIDER
    spans = _symbol_spans(active_provider, code, language)
    if not spans:
        return [_whole_file_chunk(file_path, code)]

    lines = code.splitlines(keepends=True)
    last_line_index = len(lines) - 1
    chunks: list[Chunk] = []
    for span in sorted(spans, key=lambda span: span.start_line):
        start = max(0, span.start_line - overlap_lines)
        end = min(last_line_index, span.end_line + overlap_lines)
        content = "".join(lines[start : end + 1])
        chunks.append(
            Chunk(
                file_path=file_path,
                symbol=span.name,
                start_line=start,
                end_line=end,
                content=content,
                content_hash=_hash_content(content),
            )
        )
    return chunks


def _symbol_spans(provider: RepositoryProvider, code: str, language: str) -> list[SymbolSpan]:
    """Return symbol spans from *provider* if it supports them, else an empty list.

    Args:
        provider: Provider to query; only providers exposing
            ``extract_symbol_spans`` (an optional superset of the required
            ``extract_symbols``) can produce syntax-aware boundaries.
        code: Source code to extract spans from.
        language: Language identifier passed to the provider.

    Returns:
        The provider's spans, or an empty list if unsupported or if
        extraction raises (a span-extraction failure falls back to a
        whole-file chunk rather than aborting).
    """
    extractor = getattr(provider, "extract_symbol_spans", None)
    if extractor is None:
        return []
    try:
        return list(extractor(code, language))
    except Exception:
        return []


def _whole_file_chunk(file_path: str, code: str) -> Chunk:
    """Build a single chunk covering the entire file.

    Args:
        file_path: Path of the file *code* was read from.
        code: Full source text.

    Returns:
        A :class:`Chunk` with an empty ``symbol`` spanning every line.
    """
    end_line = max(0, code.count("\n") - (1 if code.endswith("\n") else 0))
    return Chunk(
        file_path=file_path,
        symbol="",
        start_line=0,
        end_line=end_line,
        content=code,
        content_hash=_hash_content(code),
    )


def _hash_content(content: str) -> str:
    """Return the SHA-256 hex digest of *content*, used to detect unchanged chunks."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = ["Chunk", "DEFAULT_OVERLAP_LINES", "chunk_source"]
