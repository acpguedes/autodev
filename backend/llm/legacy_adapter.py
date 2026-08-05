"""Compatibility adapter for the existing text-only agent LLM provider."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from backend.llm.contracts import (
    EstimatedCost,
    ExecutionMetadata,
    MessageContent,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    NormalizedMessage,
    TokenUsage,
)
from backend.llm.errors import ModelInvalidRequestError, redacted_gateway_error
from backend.llm.model_config import ModelTarget

if TYPE_CHECKING:
    from backend.agents.provider import LLMProvider


class LegacyLLMProviderAdapter:
    """Translate normalized requests to the legacy prompt-only provider contract."""

    def __init__(self, provider: LLMProvider) -> None:
        """Store the legacy provider.

        Args:
            provider: Existing provider implementing ``complete(prompt, ...)``.
        """
        self._provider = provider

    def capabilities(self, target: ModelTarget) -> ModelCapabilities:
        """Declare the text-only legacy capability."""
        return ModelCapabilities(("text",))

    def complete(
        self,
        request: ModelRequest,
        target: ModelTarget,
        metadata: ExecutionMetadata,
    ) -> ModelResponse:
        """Execute a normalized request through the legacy provider."""
        if request.tools or request.structured_output_schema is not None:
            raise ModelInvalidRequestError(
                "legacy LLM providers support text requests only",
                provider=target.provider,
                model=target.name,
            )
        attributes = metadata.attributes
        try:
            response = self._provider.complete(
                _legacy_prompt(request),
                agent_id=_string_attribute(attributes, "agent_id"),
                run_id=_string_attribute(attributes, "run_id"),
                tenant_id=_string_attribute(attributes, "tenant_id"),
            )
        except Exception as exc:
            raise redacted_gateway_error(
                exc,
                provider=target.provider or "legacy",
                model=target.name,
            ) from None
        return ModelResponse(
            message=NormalizedMessage(
                role="assistant",
                content=(MessageContent(type="text", text=response.text),),
            ),
            usage=TokenUsage(
                input_tokens=response.tokens_input,
                output_tokens=response.tokens_output,
            ),
            cost=EstimatedCost(usd=response.cost_usd),
            metadata=ExecutionMetadata(
                provider=target.provider or "legacy",
                model=target.name,
                finish_reason="stop",
                attributes=metadata.attributes,
            ),
        )


def _legacy_prompt(request: ModelRequest) -> str:
    """Render normalized text content for a prompt-only provider."""
    rendered: list[str] = []
    for message in request.messages:
        content = "".join(_render_content(part) for part in message.content)
        if len(request.messages) == 1 and message.role == "user":
            rendered.append(content)
        else:
            rendered.append(f"{message.role}: {content}")
    return "\n".join(rendered)


def _render_content(content: MessageContent) -> str:
    """Render one internal content part without provider types."""
    if content.text is not None:
        return content.text
    return json.dumps(content.data, separators=(",", ":"), sort_keys=True)


def _string_attribute(attributes: object, key: str) -> str:
    """Read an optional string correlation attribute."""
    if isinstance(attributes, dict):
        value = attributes.get(key)
    else:
        value = getattr(attributes, "get", lambda unused: None)(key)
    return value if isinstance(value, str) else ""


__all__ = ["LegacyLLMProviderAdapter"]
