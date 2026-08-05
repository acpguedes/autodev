"""Internal state types used by governed model gateway execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.llm.contracts import AttemptTelemetry
from backend.llm.errors import ModelUnsupportedCapabilityError
from backend.llm.model_config import ModelTarget
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


__all__ = ["GatewayBudget", "PreparedTarget", "TelemetrySink"]
