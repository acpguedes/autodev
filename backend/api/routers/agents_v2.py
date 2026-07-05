"""v2 Agent Registry catalog API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.agents.registry_v2 import AgentRegistry

router = APIRouter(prefix="/v2/agents", tags=["agents"])


def get_agent_registry() -> AgentRegistry:
    """Build the agent registry dependency for request handlers.

    Returns:
        A new :class:`AgentRegistry` bound to the default durable store.
    """
    return AgentRegistry()


@router.get("/catalog")
def list_agent_catalog(
    capability: str | None = Query(default=None),
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict[str, Any]:
    """List the agent catalog, optionally filtered by capability.

    Args:
        capability: If given, restrict the catalog to agents declaring this capability.
        registry: Agent registry dependency.

    Returns:
        The catalog document as a JSON-serializable dict.
    """
    registry.sync_from_plugin_store()
    return registry.catalog(capability=capability)


__all__ = ["get_agent_registry", "router"]
