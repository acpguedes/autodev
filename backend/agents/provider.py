"""LLM provider abstraction for the v2 Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMProviderResponse:
    text: str
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0


class LLMProvider(Protocol):
    def complete(self, prompt: str, *, agent_id: str, run_id: str, tenant_id: str) -> LLMProviderResponse: ...


class StubLLMProvider:
    """Deterministic offline provider used by local-first tests and development."""

    def __init__(
        self,
        *,
        text: str = "stub response",
        tokens_input: int = 0,
        tokens_output: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        self._response = LLMProviderResponse(
            text=text,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=cost_usd,
        )

    def complete(self, prompt: str, *, agent_id: str, run_id: str, tenant_id: str) -> LLMProviderResponse:
        return self._response


__all__ = ["LLMProvider", "LLMProviderResponse", "StubLLMProvider"]
