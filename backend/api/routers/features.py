"""Feature-flag / settings inspection endpoint."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from backend.config.settings import Settings, get_settings

router = APIRouter(tags=["features"])

_REDACTED = {"openai_api_key"}


@router.get("/features", response_model=Dict[str, Any])
def get_features(settings: Settings = None) -> Dict[str, Any]:  # type: ignore[assignment]
    """Return the active settings with secrets redacted.

    Args:
        settings: Settings override for testing; falls back to :func:`get_settings`.

    Returns:
        The settings as a dict, with sensitive keys replaced by ``"***"``.
    """
    active: Settings = settings or get_settings()
    data = active.redacted_model_dump()
    for key in _REDACTED:
        if key in data and data[key]:
            data[key] = "***"
    return data
