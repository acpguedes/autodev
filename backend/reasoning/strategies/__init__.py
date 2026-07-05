"""First-party reference reasoning strategies (E4-S2/E4-S3).

Bundles the built-in strategies that ship with the platform and a helper to
register them into a :class:`~backend.reasoning.registry.ReasoningStrategyRegistry`.
Each strategy implements the ``reasoning.strategy`` contract and runs on any
provider, including the offline stub.
"""

from __future__ import annotations

from backend.reasoning.contract import ReasoningStrategy
from backend.reasoning.registry import ReasoningStrategyRegistry
from backend.reasoning.strategies.native_tools import NativeToolsStrategy
from backend.reasoning.strategies.plan_execute import PlanExecuteStrategy
from backend.reasoning.strategies.react import ReActStrategy


def builtin_strategies() -> tuple[ReasoningStrategy, ...]:
    """Return fresh instances of every built-in reference strategy.

    Returns:
        A tuple of ready-to-register strategy instances.
    """
    return (ReActStrategy(), PlanExecuteStrategy(), NativeToolsStrategy())


def register_builtin_strategies(
    registry: ReasoningStrategyRegistry, *, replace: bool = False
) -> None:
    """Register all built-in reference strategies into a registry.

    Args:
        registry: The registry to populate.
        replace: Whether to overwrite already-registered versions.
    """
    for strategy in builtin_strategies():
        registry.register(strategy, replace=replace)


__all__ = [
    "NativeToolsStrategy",
    "PlanExecuteStrategy",
    "ReActStrategy",
    "builtin_strategies",
    "register_builtin_strategies",
]
