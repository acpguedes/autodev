"""Sample skill entrypoint used by MCP HTTP transport tests (E9-S4-T1)."""

from __future__ import annotations

from typing import Any


def echo(message: str) -> dict[str, Any]:
    """Return the given message unchanged, wrapped in the skill's output shape.

    Args:
        message: The input text to echo back.

    Returns:
        A mapping with the same ``message`` value.
    """
    return {"message": message}
