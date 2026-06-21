"""Agent auto-discovery registry.

Provides a lightweight decorator-based registry so that additional agents can
be registered without modifying :mod:`backend.orchestrator.service`.

Usage::

    from backend.agents.registry import register_agent

    @register_agent("my-custom-agent")
    class MyAgent:
        name = "my-custom-agent"

        def run(self, context):
            ...

Then in the orchestrator::

    from backend.agents.registry import discover_agents
    custom = discover_agents(project_root=root)
    agents.update(custom)  # setdefault is used to avoid overriding core agents

Import errors for individual agent modules are caught and logged; they never
prevent the rest of the registry from loading.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Type

logger = logging.getLogger(__name__)

# Module-level registry: name -> class (not instantiated).
_REGISTRY: Dict[str, Type[Any]] = {}


def register_agent(name: str):
    """Class decorator that records *cls* under *name* in the global registry.

    Returns the class unchanged so it can still be used normally.
    """

    def decorator(cls: Type[Any]) -> Type[Any]:
        if name in _REGISTRY:
            logger.warning(
                "Agent name %r is already registered (by %r); overwriting with %r",
                name,
                _REGISTRY[name],
                cls,
            )
        _REGISTRY[name] = cls
        return cls

    return decorator


def discover_agents(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """Instantiate every registered agent class and return ``name -> instance``.

    If the agent constructor accepts a ``project_root`` keyword argument it is
    passed through; otherwise the agent is constructed with no arguments.

    Per-agent instantiation errors are caught, logged, and skipped — the
    remaining agents are still returned.

    Returns an empty dict when nothing has been registered.
    """
    agents: Dict[str, Any] = {}

    for name, cls in list(_REGISTRY.items()):
        try:
            sig = inspect.signature(cls.__init__)
            if "project_root" in sig.parameters and project_root is not None:
                instance = cls(project_root=project_root)
            else:
                instance = cls()
            agents[name] = instance
        except Exception:
            logger.exception("Failed to instantiate registered agent %r (%r) — skipping", name, cls)

    return agents


__all__ = ["register_agent", "discover_agents"]
