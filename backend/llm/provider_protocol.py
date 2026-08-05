"""Structural protocol for replaceable provider-neutral model adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from backend.llm.contracts import (
        ExecutionMetadata,
        ModelCapabilities,
        ModelRequest,
        ModelResponse,
        StreamChunk,
    )
    from backend.llm.model_config import ModelTarget


@runtime_checkable
class ModelProvider(Protocol):
    """Structural protocol implemented by replaceable provider adapters."""

    def capabilities(self, target: ModelTarget) -> ModelCapabilities:
        """Return capabilities declared for a target."""
        ...

    def complete(
        self,
        request: ModelRequest,
        target: ModelTarget,
        metadata: ExecutionMetadata,
    ) -> ModelResponse:
        """Execute one normalized completion request.

        Args:
            request: Provider-neutral completion request.
            target: Validated provider-neutral target.
            metadata: Provider-neutral execution correlation metadata.

        Returns:
            Provider-neutral normalized response.
        """
        ...


@runtime_checkable
class StreamingModelProvider(ModelProvider, Protocol):
    """Optional extension protocol for providers with native streaming."""

    def stream(
        self,
        request: ModelRequest,
        target: ModelTarget,
        metadata: ExecutionMetadata,
    ) -> Iterable[StreamChunk]:
        """Stream normalized chunks for one request.

        Args:
            request: Provider-neutral completion request.
            target: Validated provider-neutral target.
            metadata: Provider-neutral execution correlation metadata.

        Returns:
            An iterable of normalized response chunks.
        """
        ...


__all__ = ["ModelProvider", "StreamingModelProvider"]
