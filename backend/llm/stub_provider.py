"""Deterministic offline model provider for tests and local operation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from backend.llm.contracts import (
    EstimatedCost,
    ExecutionMetadata,
    MessageContent,
    ModelCapabilities,
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
    NormalizedMessage,
    StreamChunk,
    StructuredOutput,
    TokenUsage,
    ToolCall,
)
from backend.llm.errors import ModelInvalidRequestError, redacted_gateway_error
from backend.llm.model_config import ModelTarget


@dataclass(frozen=True)
class StubModelOutput:
    """Configurable normalized output for one stub completion."""

    text: str = "stub response"
    tool_calls: tuple[ToolCall, ...] = ()
    structured_output: StructuredOutput | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost: EstimatedCost = field(default_factory=EstimatedCost)
    finish_reason: str | None = "stop"


@dataclass(frozen=True)
class StubProviderCall:
    """Immutable record of one offline provider invocation."""

    request: ModelRequest
    target: ModelTarget
    metadata: ExecutionMetadata
    stream: bool = False


StubResult = StubModelOutput | ModelResponse | ModelGatewayError | str


class StubModelProvider:
    """Scriptable provider with no network or external-service dependency."""

    def __init__(
        self,
        *,
        responses: Mapping[str, StubResult | Sequence[StubResult]] | None = None,
        streams: Mapping[str, Sequence[StreamChunk]] | None = None,
        capabilities: Mapping[str, ModelCapabilities] | None = None,
    ) -> None:
        """Initialize deterministic per-model scripts.

        Args:
            responses: Per-model output, error, or ordered script.
            streams: Per-model ordered normalized chunks.
            capabilities: Optional per-model capability declarations.
        """
        self._responses = {
            name: self._as_script(value) for name, value in (responses or {}).items()
        }
        self._streams = {
            name: tuple(chunks) for name, chunks in (streams or {}).items()
        }
        self._capabilities = dict(capabilities or {})
        self._indices: dict[str, int] = {}
        self._calls: list[StubProviderCall] = []
        self._capability_checks: list[ModelTarget] = []

    @property
    def calls(self) -> tuple[StubProviderCall, ...]:
        """Return immutable call records."""
        return tuple(self._calls)

    @property
    def capability_checks(self) -> tuple[ModelTarget, ...]:
        """Return targets whose capabilities were inspected during preflight."""
        return tuple(self._capability_checks)

    def capabilities(self, target: ModelTarget) -> ModelCapabilities:
        """Return declared capabilities for a stub model target."""
        self._capability_checks.append(target)
        return self._capabilities.get(
            target.name,
            ModelCapabilities(
                ("text", "tool_calling", "structured_output", "streaming")
            ),
        )

    def complete(
        self,
        request: ModelRequest,
        target: ModelTarget,
        metadata: ExecutionMetadata,
    ) -> ModelResponse:
        """Return the next configured response or raise its configured error."""
        self._calls.append(StubProviderCall(request, target, metadata))
        result = self._next_result(target.name)
        if isinstance(result, ModelGatewayError):
            raise redacted_gateway_error(
                result,
                provider=target.provider or "stub",
                model=target.name,
            )
        if isinstance(result, ModelResponse):
            return replace(
                result,
                metadata=replace(
                    result.metadata,
                    provider=target.provider or "stub",
                    model=target.name,
                ),
            )
        output = StubModelOutput(text=result) if isinstance(result, str) else result
        message = NormalizedMessage(
            role="assistant",
            content=(MessageContent(type="text", text=output.text),),
            tool_calls=output.tool_calls,
        )
        return ModelResponse(
            message=message,
            usage=output.usage,
            cost=output.cost,
            metadata=ExecutionMetadata(
                provider=target.provider or "stub",
                model=target.name,
                finish_reason=output.finish_reason,
                attributes=metadata.attributes,
            ),
            structured_output=output.structured_output,
        )

    def stream(
        self,
        request: ModelRequest,
        target: ModelTarget,
        metadata: ExecutionMetadata,
    ) -> Iterable[StreamChunk]:
        """Yield configured chunks, or a single final chunk from text output."""
        self._calls.append(StubProviderCall(request, target, metadata, stream=True))
        configured = self._streams.get(target.name)
        if configured is not None:
            yield from configured
            return
        result = self._next_result(target.name)
        if isinstance(result, ModelGatewayError):
            raise redacted_gateway_error(
                result,
                provider=target.provider or "stub",
                model=target.name,
            )
        if isinstance(result, ModelResponse):
            text = "".join(part.text or "" for part in result.message.content)
            yield StreamChunk(
                index=0,
                content_delta=text,
                usage=result.usage,
                cost=result.cost,
                done=True,
            )
            return
        output = StubModelOutput(text=result) if isinstance(result, str) else result
        yield StreamChunk(
            index=0,
            content_delta=output.text,
            tool_calls=output.tool_calls,
            usage=output.usage,
            cost=output.cost,
            done=True,
        )

    @staticmethod
    def _as_script(value: StubResult | Sequence[StubResult]) -> tuple[StubResult, ...]:
        """Normalize one configured value into a non-empty script."""
        if isinstance(value, (str, ModelResponse, ModelGatewayError, StubModelOutput)):
            return (value,)
        script = tuple(value)
        if not script:
            raise ValueError("stub response scripts must not be empty")
        return script

    def _next_result(self, model: str) -> StubResult:
        """Return the next result, repeating the final script entry."""
        script = self._responses.get(model)
        if script is None:
            raise ModelInvalidRequestError(
                f"stub model '{model}' has no configured response",
                provider="stub",
                model=model,
            )
        index = self._indices.get(model, 0)
        self._indices[model] = index + 1
        return script[min(index, len(script) - 1)]


__all__ = ["StubModelOutput", "StubModelProvider", "StubProviderCall"]
