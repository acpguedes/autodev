"""Feature-flag / settings inspection endpoint."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from backend.config.settings import Settings, get_settings

router = APIRouter(tags=["features"])


@router.get("/features", response_model=Dict[str, Any])
def get_features(settings: Settings = None) -> Dict[str, Any]:  # type: ignore[assignment]
    """Return the active settings with secrets redacted.

    Args:
        settings: Settings override for testing; falls back to :func:`get_settings`.

    Returns:
        The settings as a dict, with sensitive keys replaced by ``"***"``.
        ``Settings.redacted_model_dump()`` is the sole redaction policy; this
        endpoint does not apply a second, independently maintained mask list.
    """
    active: Settings = settings or get_settings()
    return active.redacted_model_dump()
