"""Provider-neutral contracts for model execution.

The types in this module deliberately contain no provider SDK or LangChain
objects. Adapters translate at this boundary so callers, telemetry, and stored
results remain portable across hosted and local model providers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Literal, Mapping, Protocol, Sequence, TypeAlias, runtime_checkable

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | Sequence["JSONValue"] | Mapping[str, "JSONValue"]
JSONMapping: TypeAlias = Mapping[str, JSONValue]

MessageRole: TypeAlias = Literal["system", "user", "assistant", "tool"]
ContentType: TypeAlias = Literal["text", "json", "image"]
ModelCapabilityId: TypeAlias = Literal["text", "tool_calling", "structured_output", "streaming"]
ModelErrorCode: TypeAlias = Literal[
    "provider_not_configured",
    "unsupported_capability",
    "authentication",
    "invalid_request",
    "timeout",
    "rate_limit",
    "unavailable",
    "budget_exceeded",
    "provider_error",
]

MODEL_CAPABILITY_IDS = frozenset({"text", "tool_calling", "structured_output", "streaming"})
MODEL_ERROR_CODES = frozenset(
    {
        "provider_not_configured",
        "unsupported_capability",
        "authentication",
        "invalid_request",
        "timeout",
        "rate_limit",
        "unavailable",
        "budget_exceeded",
        "provider_error",
    }
)


def _freeze_json(value: object, *, path: str = "$") -> JSONValue:
    """Convert a JSON-like value into a recursively immutable representation.

    Args:
        value: Candidate JSON-compatible value.
        path: Path used to identify invalid nested values.

    Returns:
        An immutable JSON scalar, tuple, or read-only mapping.

    Raises:
        TypeError: If the value is not JSON-compatible or has a non-string key.
        ValueError: If a floating-point value is not finite.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} must contain only string object keys")
            frozen[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, path=f"{path}[{index}]") for index, item in enumerate(value))
    raise TypeError(f"{path} contains unsupported JSON value {type(value).__name__}")


def _freeze_mapping(value: Mapping[str, object], *, path: str) -> JSONMapping:
    """Freeze a mapping and retain its mapping-specific return type.

    Args:
        value: JSON-like mapping to freeze.
        path: Path used in validation messages.

    Returns:
        A recursively immutable mapping.
    """
    frozen = _freeze_json(value, path=path)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guaranteed by the input type
        raise TypeError(f"{path} must be a mapping")
    return frozen


@dataclass(frozen=True)
class MessageContent:
    """One normalized content part in a model message.

    Attributes:
        type: Portable content kind.
        text: Text content when ``type`` is ``"text"``.
        data: JSON-like content or image descriptor.
        mime_type: Optional media type for image content.
    """

    type: ContentType
    text: str | None = None
    data: JSONValue = None
    mime_type: str | None = None

    def __post_init__(self) -> None:
        """Freeze nested JSON content after construction."""
        object.__setattr__(self, "data", _freeze_json(self.data, path="message.content.data"))


@dataclass(frozen=True)
class ToolCall:
    """Normalized request by a model to invoke a tool.

    Attributes:
        id: Provider-independent call correlation id.
        name: Tool name from the request's tool catalog.
        arguments: Immutable JSON-like arguments.
    """

    id: str
    name: str
    arguments: JSONMapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze tool arguments after construction."""
        object.__setattr__(self, "arguments", _freeze_mapping(self.arguments, path="tool.arguments"))


@dataclass(frozen=True)
class NormalizedMessage:
    """A model message normalized across provider-specific wire formats.

    Attributes:
        role: Portable conversation role.
        content: Ordered immutable content parts.
        name: Optional participant or tool name.
        tool_call_id: Tool call correlated with a tool result message.
        tool_calls: Tool requests emitted by an assistant message.
        metadata: Provider-neutral JSON-like annotations.
    """

    role: MessageRole
    content: tuple[MessageContent, ...]
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    metadata: JSONMapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Copy ordered fields and freeze message metadata after construction."""
        object.__setattr__(self, "content", tuple(self.content))
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, path="message.metadata"))


@dataclass(frozen=True)
class ToolDefinition:
    """Tool declaration made available to a model.

    Attributes:
        name: Stable tool name.
        description: Human-readable behavior description.
        input_schema: JSON Schema for tool arguments.
    """

    name: str
    description: str
    input_schema: JSONMapping

    def __post_init__(self) -> None:
        """Freeze the input schema after construction."""
        object.__setattr__(self, "input_schema", _freeze_mapping(self.input_schema, path="tool.input_schema"))


@dataclass(frozen=True)
class TokenUsage:
    """Normalized token accounting for one model response.

    Attributes:
        input_tokens: Tokens supplied to the model.
        output_tokens: Tokens generated by the model.
        cached_input_tokens: Input tokens served from provider cache.
        reasoning_tokens: Provider-reported internal reasoning tokens.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Return input plus output tokens without double-counting subcategories."""
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class EstimatedCost:
    """Estimated monetary cost of a model response.

    Attributes:
        usd: Estimated cost in US dollars.
        estimated: Whether the amount is an estimate rather than provider-billed cost.
    """

    usd: float = 0.0
    estimated: bool = True


@dataclass(frozen=True)
class StructuredOutput:
    """Provider-neutral structured output returned by a model.

    Attributes:
        value: Immutable JSON-like output value.
        schema_name: Optional logical schema identifier.
    """

    value: JSONValue
    schema_name: str | None = None

    def __post_init__(self) -> None:
        """Freeze the structured value after construction."""
        object.__setattr__(self, "value", _freeze_json(self.value, path="structured_output.value"))


@dataclass(frozen=True)
class ExecutionMetadata:
    """Normalized metadata about one provider execution.

    Attributes:
        provider: Adapter/provider identifier.
        model: Provider model identifier.
        request_id: Optional provider request id for support correlation.
        finish_reason: Optional normalized completion reason.
        latency_ms: End-to-end provider latency in milliseconds.
        attributes: Additional provider-neutral JSON-like metadata.
    """

    provider: str
    model: str
    request_id: str | None = None
    finish_reason: str | None = None
    latency_ms: float | None = None
    attributes: JSONMapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze execution attributes after construction."""
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes, path="execution.attributes"))


@dataclass(frozen=True)
class ModelRequest:
    """Provider-neutral model completion request.

    Attributes:
        messages: Ordered normalized conversation messages.
        tools: Tools available to the model.
        structured_output_schema: Optional JSON Schema requested for the response.
        metadata: Caller-owned tracing and policy annotations.
    """

    messages: tuple[NormalizedMessage, ...]
    tools: tuple[ToolDefinition, ...] = ()
    structured_output_schema: JSONMapping | None = None
    metadata: JSONMapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Copy ordered fields and freeze request mappings after construction."""
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        if self.structured_output_schema is not None:
            object.__setattr__(
                self,
                "structured_output_schema",
                _freeze_mapping(self.structured_output_schema, path="request.structured_output_schema"),
            )
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, path="request.metadata"))


@dataclass(frozen=True)
class ModelResponse:
    """Complete normalized response from one model attempt.

    Attributes:
        message: Assistant message returned by the model.
        usage: Normalized token accounting.
        cost: Estimated execution cost.
        metadata: Provider execution metadata.
        structured_output: Optional parsed structured result.
    """

    message: NormalizedMessage
    usage: TokenUsage
    cost: EstimatedCost
    metadata: ExecutionMetadata
    structured_output: StructuredOutput | None = None


@dataclass(frozen=True)
class StreamChunk:
    """Normalized incremental model response.

    Attributes:
        index: Zero-based chunk order.
        content_delta: Incremental text content.
        tool_calls: Incremental or completed normalized tool calls.
        usage: Usage snapshot when the provider reports it.
        done: Whether this is the final stream chunk.
    """

    index: int
    content_delta: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage | None = None
    done: bool = False

    def __post_init__(self) -> None:
        """Copy tool calls so callers cannot mutate the chunk."""
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))


@dataclass(frozen=True)
class AttemptTelemetry:
    """Immutable telemetry for one provider attempt.

    Attributes:
        attempt: One-based attempt number.
        provider: Provider identifier.
        model: Model identifier.
        duration_ms: Attempt duration in milliseconds.
        usage: Token usage reported for the attempt.
        cost: Estimated attempt cost.
        error_code: Normalized failure code, if the attempt failed.
    """

    attempt: int
    provider: str
    model: str
    duration_ms: float
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost: EstimatedCost = field(default_factory=EstimatedCost)
    error_code: ModelErrorCode | None = None


@dataclass(frozen=True)
class ModelCapabilities:
    """Capabilities advertised by a model provider target.

    Attributes:
        supported: Stable capability identifiers supported by the target.
    """

    supported: tuple[ModelCapabilityId, ...] = ("text",)

    def __post_init__(self) -> None:
        """Copy capability ids so callers cannot mutate the advertised set."""
        object.__setattr__(self, "supported", tuple(self.supported))

    def supports(self, capability: str) -> bool:
        """Return whether a capability identifier is supported.

        Args:
            capability: Capability identifier to query.

        Returns:
            ``True`` when the capability appears in :attr:`supported`.
        """
        return capability in self.supported


@runtime_checkable
class ModelProvider(Protocol):
    """Structural protocol implemented by replaceable provider adapters."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Execute one normalized completion request.

        Args:
            request: Provider-neutral completion request.

        Returns:
            Provider-neutral normalized response.
        """
        ...


@runtime_checkable
class StreamingModelProvider(ModelProvider, Protocol):
    """Optional extension protocol for providers with native streaming."""

    def stream(self, request: ModelRequest) -> Iterable[StreamChunk]:
        """Stream normalized chunks for one request.

        Args:
            request: Provider-neutral completion request.

        Returns:
            An iterable of normalized response chunks.
        """
        ...


class ModelGatewayError(RuntimeError):
    """Base error normalized at the provider-neutral boundary."""

    code: ModelErrorCode
    retryable: bool

    def __init__(self, message: str, *, provider: str | None = None, model: str | None = None) -> None:
        """Initialize a typed provider error.

        Args:
            message: Human-readable error description without credentials.
            provider: Provider identifier, when known.
            model: Model identifier, when known.
        """
        super().__init__(message)
        self.provider = provider
        self.model = model


class ModelTimeoutError(ModelGatewayError):
    """Provider attempt exceeded its configured timeout."""

    code: ModelErrorCode = "timeout"
    retryable = True


class ModelRateLimitError(ModelGatewayError):
    """Provider rejected an attempt because of rate limiting."""

    code: ModelErrorCode = "rate_limit"
    retryable = True


class ModelUnavailableError(ModelGatewayError):
    """Provider or model target was temporarily unavailable."""

    code: ModelErrorCode = "unavailable"
    retryable = True


__all__ = [
    "AttemptTelemetry",
    "ContentType",
    "EstimatedCost",
    "ExecutionMetadata",
    "JSONMapping",
    "JSONScalar",
    "JSONValue",
    "MODEL_CAPABILITY_IDS",
    "MODEL_ERROR_CODES",
    "MessageContent",
    "MessageRole",
    "ModelCapabilities",
    "ModelCapabilityId",
    "ModelErrorCode",
    "ModelGatewayError",
    "ModelProvider",
    "ModelRateLimitError",
    "ModelRequest",
    "ModelResponse",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "NormalizedMessage",
    "StreamChunk",
    "StreamingModelProvider",
    "StructuredOutput",
    "TokenUsage",
    "ToolCall",
    "ToolDefinition",
]
