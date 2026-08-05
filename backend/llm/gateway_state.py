"""Internal state types used by governed model gateway execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.llm.contracts import AttemptTelemetry
from backend.llm.errors import ModelBudgetExceededError, ModelUnsupportedCapabilityError
from backend.llm.model_config import ModelLimits, ModelTarget
from backend.llm.provider_protocol import ModelProvider

TelemetrySink = Callable[[AttemptTelemetry], None]


@dataclass
class GatewayBudget:
    """Mutable aggregate accounting local to one gateway call."""

    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class PreparedTarget:
    """Preflight result for one ordered model target."""

    target: ModelTarget
    provider: ModelProvider
    capability_error: ModelUnsupportedCapabilityError | None = None


def check_call_limit(
    limits: ModelLimits, budget: GatewayBudget, target: ModelTarget
) -> None:
    """Fail before invoking a call beyond the configured ceiling."""
    if limits.max_calls is not None and budget.calls >= limits.max_calls:
        raise ModelBudgetExceededError(
            "model call limit exceeded",
            provider=target.provider,
            model=target.name,
        )


def check_usage_limits(
    limits: ModelLimits, budget: GatewayBudget, target: ModelTarget
) -> None:
    """Fail closed after a response crosses token or cost ceilings."""
    if limits.max_total_tokens is not None and budget.tokens > limits.max_total_tokens:
        raise ModelBudgetExceededError(
            "model token limit exceeded",
            provider=target.provider,
            model=target.name,
        )
    if limits.max_cost_usd is not None and budget.cost_usd > limits.max_cost_usd:
        raise ModelBudgetExceededError(
            "model cost limit exceeded",
            provider=target.provider,
            model=target.name,
        )


__all__ = [
    "GatewayBudget",
    "PreparedTarget",
    "TelemetrySink",
    "check_call_limit",
    "check_usage_limits",
]
