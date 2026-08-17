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


def parse_iso(value: str) -> float:
    """Parse an ISO-8601 timestamp back to a Unix timestamp."""
    return datetime.fromisoformat(value).timestamp()


__all__ = ["iso", "now_plus", "parse_iso"]
