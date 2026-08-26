"""Small timestamp helpers shared by :mod:`backend.quotas.store`."""

from __future__ import annotations

import time
from datetime import datetime, timezone


def iso(unix_seconds: float) -> str:
    """Format a Unix timestamp as an ISO-8601 UTC string."""
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()


def now_plus(seconds: int) -> str:
    """Return an ISO-8601 UTC timestamp ``seconds`` in the future."""
    return iso(time.time() + seconds)


def parse_iso(value: str | datetime) -> float:
    """Parse an ISO-8601 timestamp back to a Unix timestamp.

    Args:
        value: A timestamp as read back from a ``TEXT`` (SQLite) or
            ``TIMESTAMPTZ`` (PostgreSQL) column. SQLite always returns
            ``str``; psycopg decodes ``TIMESTAMPTZ`` to an already-aware
            :class:`datetime` before this ever runs (E51) -- both accepted
            directly.
    """
    if isinstance(value, datetime):
        return value.timestamp()
    return datetime.fromisoformat(value).timestamp()


def normalize(value: str | datetime) -> str:
    """Return a raw timestamp column value as an ISO-8601 string, regardless of dialect.

    Args:
        value: A timestamp as read back from a ``TEXT`` (SQLite) or
            ``TIMESTAMPTZ`` (PostgreSQL) column -- see :func:`parse_iso`.

    Returns:
        The value as an ISO-8601 string.
    """
    return value.isoformat() if isinstance(value, datetime) else value


__all__ = ["iso", "normalize", "now_plus", "parse_iso"]
