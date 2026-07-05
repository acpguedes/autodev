"""LLM provider abstraction for the v2 Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMProviderResponse:
    """Result of a single LLM completion call.

    Attributes:
        text: Completion text returned by the provider.
        tokens_input: Number of input (prompt) tokens consumed.
        tokens_output: Number of output (completion) tokens produced.
        cost_usd: Estimated cost of the call in US dollars.
    """

    text: str
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0


class LLMProvider(Protocol):
    """Structural interface for LLM backends used by the agent runtime."""

    def complete(self, prompt: str, *, agent_id: str, run_id: str, tenant_id: str) -> LLMProviderResponse:
        """Generate a completion for the given prompt.

        Args:
            prompt: Fully rendered prompt text to send to the model.
            agent_id: Identifier of the agent issuing the request.
            run_id: Identifier of the run the request belongs to.
            tenant_id: Identifier of the tenant the request is scoped to.

        Returns:
            The provider's completion response.
        """
        ...


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
        """Initialize the stub with a fixed response to return for every call.

        Args:
            text: Completion text to return.
            tokens_input: Fixed input token count to report.
            tokens_output: Fixed output token count to report.
            cost_usd: Fixed cost in US dollars to report.
        """
        self._response = LLMProviderResponse(
            text=text,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=cost_usd,
        )

    def complete(self, prompt: str, *, agent_id: str, run_id: str, tenant_id: str) -> LLMProviderResponse:
        """Return the fixed response configured at construction time.

        Args:
            prompt: Prompt text (ignored by the stub).
            agent_id: Identifier of the agent issuing the request (ignored).
            run_id: Identifier of the run the request belongs to (ignored).
            tenant_id: Identifier of the tenant the request is scoped to (ignored).

        Returns:
            The fixed :class:`LLMProviderResponse` configured at construction.
        """
        return self._response


__all__ = ["LLMProvider", "LLMProviderResponse", "StubLLMProvider"]
