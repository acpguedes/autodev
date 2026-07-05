"""Plugin Control Plane API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.plugins.registry import ActivePluginRegistry

router = APIRouter(prefix="/v2/plugins", tags=["plugins"])


def get_active_plugin_registry() -> ActivePluginRegistry:
    """Build the active plugin registry dependency for request handlers.

    Returns:
        A new :class:`ActivePluginRegistry`.
    """
    return ActivePluginRegistry()


@router.get("/active")
def list_active_plugins(
    registry: ActivePluginRegistry = Depends(get_active_plugin_registry),
) -> dict[str, Any]:
    """List currently active plugins.

    Args:
        registry: Active plugin registry dependency.

    Returns:
        A snapshot of active plugins as a JSON-serializable dict.
    """
    return registry.snapshot()


__all__ = ["get_active_plugin_registry", "router"]
