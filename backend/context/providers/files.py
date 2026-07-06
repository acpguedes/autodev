"""Files-based ``ContextProvider`` (E7-S4 example provider).

Reads a fixed list of files from disk and returns their content as
attributable context items — the simplest possible provider implementation,
mainly useful as a reference and for tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.context.provider import ContextItem


class FilesContextProvider:
    """Context provider surfacing the full content of a fixed set of files."""

    provider_id = "files"

    def __init__(self, paths: list[str | Path]) -> None:
        """Initialize the provider with the files it will surface.

        Args:
            paths: Paths to read and return as context items.
        """
        self._paths = [Path(path) for path in paths]

    def get_context(self, query: str, **kwargs: Any) -> list[ContextItem]:
        """Return one context item per configured file that exists and is readable.

        Args:
            query: Accepted for Protocol compatibility; unused — this
                provider always returns its full configured file set.
            **kwargs: Accepted for Protocol compatibility; ignored.

        Returns:
            One :class:`ContextItem` per existing, readable file, attributed
            with its path; a file that does not exist or cannot be decoded
            as UTF-8 text is silently skipped rather than raising — an
            optional/missing file is an expected case for a fixed path list,
            not a provider failure.
        """
        del query, kwargs
        items: list[ContextItem] = []
        for path in self._paths:
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            items.append(
                ContextItem(
                    content=content,
                    source=self.provider_id,
                    score=1.0,
                    metadata={"path": str(path)},
                )
            )
        return items


__all__ = ["FilesContextProvider"]
