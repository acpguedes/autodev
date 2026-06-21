"""Repository intelligence providers.

A provider implements the :class:`RepositoryProvider` Protocol, exposing a
single method::

    extract_symbols(code: str, language: str) -> list[str]

The default provider is :class:`LexicalProvider`.  Set the environment variable
``AUTODEV_REPO_PROVIDER=treesitter`` to opt into :class:`TreeSitterProvider`
(requires the ``tree_sitter`` library to be installed).
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from backend.repository.providers.lexical_provider import LexicalProvider
from backend.repository.providers.treesitter_provider import TreeSitterProvider


@runtime_checkable
class RepositoryProvider(Protocol):
    """Structural Protocol for repository symbol extractors."""

    def extract_symbols(self, code: str, language: str) -> list[str]:
        """Return a list of symbol names found in *code*."""
        ...


def get_provider() -> RepositoryProvider:
    """Return the active provider based on the environment.

    Returns :class:`TreeSitterProvider` only when **both** conditions hold:

    1. The ``tree_sitter`` package is importable (optional dependency).
    2. ``AUTODEV_REPO_PROVIDER`` is set to ``"treesitter"`` (case-insensitive).

    Otherwise returns :class:`LexicalProvider`.
    """
    want_treesitter = (
        os.environ.get("AUTODEV_REPO_PROVIDER", "").strip().lower() == "treesitter"
    )
    if want_treesitter:
        try:
            import tree_sitter  # type: ignore[import-untyped]  # noqa: F401

            return TreeSitterProvider()
        except ImportError:
            pass
    return LexicalProvider()


__all__ = [
    "RepositoryProvider",
    "LexicalProvider",
    "TreeSitterProvider",
    "get_provider",
]
