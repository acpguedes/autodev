"""Plugin Control Plane API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.plugins.registry import ActivePluginRegistry

router = APIRouter(prefix="/v2/plugins", tags=["plugins"])


def get_active_plugin_registry() -> ActivePluginRegistry:
    return ActivePluginRegistry()


@router.get("/active")
def list_active_plugins(
    registry: ActivePluginRegistry = Depends(get_active_plugin_registry),
) -> dict[str, Any]:
    return registry.snapshot()


__all__ = ["get_active_plugin_registry", "router"]
