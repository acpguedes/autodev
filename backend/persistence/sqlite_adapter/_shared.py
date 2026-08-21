"""Path resolution and the connection-owner typing base shared across submodules."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"


def _resolve_db_path(database_url: str) -> Path:
    url = (database_url or _DEFAULT_DATABASE_URL).strip()
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
    elif url.startswith("sqlite://"):
        raw = url.removeprefix("sqlite://")
    else:
        raise ValueError(
            f"SQLiteStore requires a sqlite:// DATABASE_URL. Got: {url!r}"
        )
    return Path(raw).expanduser().resolve()


class _ConnectionOwner:
    """Typing base for ``SQLiteStore``'s mixins: declares the ``connect()`` every mixin calls.

    ``SQLiteStore`` (in :mod:`store`) provides the real implementation; this
    placeholder exists only so each mixin can be read, and type-checked, on
    its own without depending on the composed class.
    """

    database_url: str

    def connect(self) -> sqlite3.Connection:  # pragma: no cover - overridden by SQLiteStore
        raise NotImplementedError


__all__ = ["_ConnectionOwner", "_DEFAULT_DATABASE_URL", "_resolve_db_path"]
