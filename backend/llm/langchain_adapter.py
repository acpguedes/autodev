"""Replaceable LangChain adapter contained behind AutoDev model contracts."""

from __future__ import annotations

import inspect
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, cast

import httpx

from backend.llm.contracts import (
    EstimatedCost,
    ExecutionMetadata,
    MessageContent,
    ModelCapabilities,
    ModelGatewayError,
    ModelRequest,
    ModelRateLimitError,
    ModelResponse,
    ModelTimeoutError,
    ModelUnavailableError,
    NormalizedMessage,
    StreamChunk,
    StructuredOutput,
    TokenUsage,
    ToolCall,
)
from backend.llm.errors import (
    ModelAuthenticationError,
    ModelInvalidRequestError,
    ModelProviderError,
    ModelUnsupportedCapabilityError,
    redact_error_message,
    redacted_gateway_error,
)
from backend.llm.factory import LLMConfigurationError, get_chat_model
from backend.llm.model_config import ModelTarget

_SUPPORTED_PROVIDERS = frozenset({"openai", "ollama"})


class _Runnable(Protocol):
    """Narrow structural view of the LangChain methods used by this adapter."""

    def invoke(self, messages: object) -> object:
        """Invoke a complete chat call."""
        ...

    def stream(self, messages: object) -> Iterable[object]:
        """Stream chat chunks."""
        ...


class LangChainModelProvider:
    """Normalize supported LangChain chat models behind the gateway protocol."""

    def __init__(
        self,
        provider_id: str,
        *,
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        """Initialize a fail-closed provider adapter.

        Args:
            provider_id: ``openai`` or ``ollama``.
            capabilities: Registered capabilities for models served by this adapter.

        Raises:
            ModelInvalidRequestError: If the provider is unsupported.
        """
        if provider_id not in _SUPPORTED_PROVIDERS:
            raise ModelInvalidRequestError(
                f"unsupported LangChain provider '{provider_id}'"
            )
        self.provider_id = provider_id
        self._capabilities = capabilities or ModelCapabilities(
            ("text", "tool_calling", "structured_output", "streaming")
        )

    def capabilities(self, target: ModelTarget) -> ModelCapabilities:
        """Return the capabilities registered for this adapter."""
        return self._capabilities

    def complete(
        self,
        request: ModelRequest,
        target: ModelTarget,
        metadata: ExecutionMetadata,
    ) -> ModelResponse:
        """Invoke LangChain and normalize its complete response."""
        try:
            model = self._model(target)
            messages = _langchain_messages(request)
            structured: StructuredOutput | None = None
            if request.structured_output_schema is not None:
                runnable = cast(_Runnable, _structured_runnable(model, request))
                native = runnable.invoke(messages)
                raw, structured = _native_structured_response(native)
            else:
                runnable = cast(_Runnable, _bind_tools(model, request))
                raw = runnable.invoke(messages)
            return _normalize_response(raw, target, metadata, structured)
        except Exception as exc:
            raise _normalize_exception(exc, target) from None

    def stream(
        self,
        request: ModelRequest,
        target: ModelTarget,
        metadata: ExecutionMetadata,
    ) -> Iterable[StreamChunk]:
        """Stream LangChain chunks normalized to the internal chunk contract.

        Each provider chunk is yielded as soon as it arrives, so first-token
        delivery is never delayed by a look-ahead read. The stream closes with a
        terminal chunk carrying the final usage and cost snapshot.

        Raises:
            ModelUnsupportedCapabilityError: If the request asks for structured
                output, which this adapter cannot honor while streaming.
        """
        try:
            if request.structured_output_schema is not None:
                raise ModelUnsupportedCapabilityError(
                    "streamed native structured output is not supported",
                    provider=target.provider,
                    model=target.name,
                )
            model = self._model(target)
            runnable = cast(_Runnable, _bind_tools(model, request))
            index = 0
            usage: TokenUsage | None = None
            cost: EstimatedCost | None = None
            for raw in runnable.stream(_langchain_messages(request)):
                chunk = _normalize_chunk(raw, index=index)
                usage = chunk.usage if chunk.usage is not None else usage
                cost = chunk.cost if chunk.cost is not None else cost
                yield chunk
                index += 1
            yield StreamChunk(index=index, usage=usage, cost=cost, done=True)
        except Exception as exc:
            raise _normalize_exception(exc, target) from None

    def _model(self, target: ModelTarget) -> object:
        """Construct a real model with permissive stub fallback disabled."""
        return get_chat_model(
            provider=self.provider_id,
            model=target.name,
            temperature=target.temperature,
            max_tokens=target.max_tokens,
            request_timeout=target.timeout_seconds,
            allow_stub=False,
        )


def _langchain_messages(request: ModelRequest) -> list[object]:
    """Translate internal messages while keeping LangChain types in this module."""
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    messages: list[object] = []
    for message in request.messages:
        content = _message_content(message)
        if message.role == "system":
            messages.append(SystemMessage(content=content, name=message.name))
        elif message.role == "user":
            messages.append(HumanMessage(content=content, name=message.name))
        elif message.role == "tool":
            messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=message.tool_call_id or "",
                    name=message.name,
                )
            )
        else:
            messages.append(
                AIMessage(
                    content=content,
                    name=message.name,
                    tool_calls=[
                        {"id": call.id, "name": call.name, "args": dict(call.arguments)}
                        for call in message.tool_calls
                    ],
                )
            )
    return messages


def _message_content(message: NormalizedMessage) -> Any:
    """Translate internal content parts to LangChain-compatible content."""
    if all(part.type == "text" for part in message.content):
        return "".join(part.text or "" for part in message.content)
    parts: list[dict[str, object]] = []
    for part in message.content:
        if part.type == "text":
            parts.append({"type": "text", "text": part.text or ""})
        elif part.type == "json":
            parts.append(
                {"type": "text", "text": json.dumps(part.data, sort_keys=True)}
            )
        else:
            parts.append({"type": "image_url", "image_url": part.data})
    return parts


def _bind_tools(model: object, request: ModelRequest) -> object:
    """Bind normalized tool definitions when the request declares tools."""
    if not request.tools:
        return model
    definitions = _tool_definitions(request)
    binder = getattr(model, "bind_tools", None)
    if not callable(binder):
        raise ModelInvalidRequestError("configured model does not support tool binding")
    return binder(definitions)


def _tool_definitions(request: ModelRequest) -> list[dict[str, object]]:
    """Translate internal tool definitions for the contained LangChain boundary."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.input_schema),
            },
        }
        for tool in request.tools
    ]


def _accepts_keyword(
    target: object, name: str, *, require_explicit: bool = False
) -> bool:
    """Return whether a callable can receive a named keyword argument.

    Args:
        target: Callable to introspect.
        name: Keyword argument name.
        require_explicit: When ``True``, a ``**kwargs`` catch-all does not count
            as support. Use this for arguments whose effect cannot be verified
            afterwards: ``**kwargs`` would swallow them silently, which is
            indistinguishable from the provider honoring them.

    Returns:
        Whether the keyword can be forwarded. When the callable cannot be
        introspected, an explicitly-required keyword is treated as unsupported
        and any other keyword is left for the provider to validate.
    """
    try:
        parameters = inspect.signature(target).parameters  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return not require_explicit
    parameter = parameters.get(name)
    if parameter is not None and parameter.kind in {
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }:
        return True
    if require_explicit:
        return False
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _structured_runnable(model: object, request: ModelRequest) -> object:
    """Select LangChain's native provider structured-output mode.

    Only arguments the concrete provider actually declares are forwarded, and any
    gap is reported as a capability error so the gateway can fall back explicitly
    instead of degrading silently.

    Raises:
        ModelUnsupportedCapabilityError: If the provider cannot express native
            structured output, cannot return the raw envelope, or cannot combine
            structured output with the requested tools.
    """
    structured = getattr(model, "with_structured_output", None)
    if not callable(structured) or request.structured_output_schema is None:
        raise ModelUnsupportedCapabilityError(
            "configured model does not support native structured output"
        )
    if not _accepts_keyword(structured, "include_raw"):
        raise ModelUnsupportedCapabilityError(
            "configured model cannot return a raw native structured response"
        )
    kwargs: dict[str, object] = {"include_raw": True}
    if request.tools:
        if not _accepts_keyword(structured, "tools", require_explicit=True):
            raise ModelUnsupportedCapabilityError(
                "configured model cannot combine tool calling with native "
                "structured output"
            )
        kwargs["tools"] = _tool_definitions(request)
    return structured(dict(request.structured_output_schema), **kwargs)


def _native_structured_response(
    native: object,
) -> tuple[object, StructuredOutput | None]:
    """Consume LangChain's include-raw native structured result.

    Raises:
        ModelUnsupportedCapabilityError: If the provider ignored ``include_raw``
            and returned no raw response to normalize.
        ModelInvalidRequestError: If the model produced unparsable structured
            output.
    """
    result = _mapping(native)
    raw = result.get("raw")
    if raw is None:
        raise ModelUnsupportedCapabilityError(
            "native structured output did not include a raw response"
        )
    if result.get("parsing_error") is not None:
        raise ModelInvalidRequestError("model returned invalid structured output")
    parsed = result.get("parsed")
    if parsed is None:
        return raw, None
    model_dump = getattr(parsed, "model_dump", None)
    if callable(model_dump):
        parsed = model_dump(mode="json")
    return raw, StructuredOutput(value=parsed)  # type: ignore[arg-type]


def _normalize_response(
    raw: object,
    target: ModelTarget,
    metadata: ExecutionMetadata,
    structured: StructuredOutput | None,
) -> ModelResponse:
    """Translate a LangChain message into the complete internal response."""
    response_metadata = _mapping(getattr(raw, "response_metadata", {}))
    usage = _usage(raw, response_metadata)
    content = getattr(raw, "content", "")
    text = content if isinstance(content, str) else json.dumps(content, sort_keys=True)
    cost = _estimated_cost(raw, response_metadata)
    return ModelResponse(
        message=NormalizedMessage(
            role="assistant",
            content=(MessageContent(type="text", text=text),),
            tool_calls=_tool_calls(getattr(raw, "tool_calls", ())),
        ),
        usage=usage,
        cost=cost or EstimatedCost(),
        metadata=ExecutionMetadata(
            provider=target.provider or "",
            model=target.name,
            request_id=_optional_string(response_metadata.get("request_id")),
            finish_reason=_optional_string(response_metadata.get("finish_reason")),
            attributes=metadata.attributes,
        ),
        structured_output=structured,
    )


def _normalize_chunk(raw: object, *, index: int) -> StreamChunk:
    """Translate one LangChain streaming chunk into a non-terminal chunk."""
    content = getattr(raw, "content", "")
    text = content if isinstance(content, str) else json.dumps(content, sort_keys=True)
    metadata = _mapping(getattr(raw, "response_metadata", {}))
    return StreamChunk(
        index=index,
        content_delta=text,
        tool_calls=_tool_calls(getattr(raw, "tool_calls", ())),
        usage=_reported_usage(raw, metadata),
        cost=_estimated_cost(raw, metadata),
        done=False,
    )


def _reported_usage(
    raw: object, response_metadata: Mapping[str, object]
) -> TokenUsage | None:
    """Return a usage snapshot only when the provider actually reported one."""
    if not _mapping(getattr(raw, "usage_metadata", {})) and not _mapping(
        response_metadata.get("token_usage", {})
    ):
        return None
    return _usage(raw, response_metadata)


def _usage(raw: object, response_metadata: Mapping[str, object]) -> TokenUsage:
    """Normalize LangChain usage metadata across supported response shapes."""
    usage = _mapping(getattr(raw, "usage_metadata", {}))
    if not usage:
        usage = _mapping(response_metadata.get("token_usage", {}))
    return TokenUsage(
        input_tokens=_integer(usage.get("input_tokens", usage.get("prompt_tokens", 0))),
        output_tokens=_integer(
            usage.get("output_tokens", usage.get("completion_tokens", 0))
        ),
        cached_input_tokens=_integer(usage.get("cached_input_tokens", 0)),
        reasoning_tokens=_integer(usage.get("reasoning_tokens", 0)),
    )


def _tool_calls(raw_calls: object) -> tuple[ToolCall, ...]:
    """Normalize LangChain tool-call mappings."""
    if not isinstance(raw_calls, (list, tuple)):
        return ()
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        mapping = _mapping(raw)
        arguments = mapping.get("args", mapping.get("arguments", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        calls.append(
            ToolCall(
                id=str(mapping.get("id", f"call-{index}")),
                name=str(mapping.get("name", "")),
                arguments=_mapping(arguments),
            )
        )
    return tuple(calls)


def _estimated_cost(
    raw: object, response_metadata: Mapping[str, object]
) -> EstimatedCost | None:
    """Normalize an estimated-cost snapshot when provider metadata reports one."""
    usage = _mapping(getattr(raw, "usage_metadata", {}))
    for source in (usage, response_metadata):
        for key in ("estimated_cost_usd", "cost_usd"):
            value = source.get(key)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            ):
                return EstimatedCost(float(value))
    return None


def _normalize_exception(error: Exception, target: ModelTarget) -> Exception:
    """Map configuration, HTTP, and provider failures to stable typed errors."""
    if isinstance(error, ModelGatewayError):
        return redacted_gateway_error(
            error,
            provider=target.provider or "",
            model=target.name,
        )
    message = redact_error_message(error)
    kwargs = {"provider": target.provider, "model": target.name}
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return ModelTimeoutError(message, **kwargs)
    status = _status_code(error)
    if status == 429:
        return ModelRateLimitError(message, **kwargs)
    if status in {401, 403}:
        return ModelAuthenticationError(message, **kwargs)
    if status == 400:
        return ModelInvalidRequestError(message, **kwargs)
    if isinstance(status, int) and status >= 500:
        return ModelUnavailableError(message, **kwargs)
    lowered = str(error).lower()
    if isinstance(error, LLMConfigurationError) or any(
        marker in lowered
        for marker in ("api_key", "api key", "credential", "authentication")
    ):
        return ModelAuthenticationError(message, **kwargs)
    return ModelProviderError(message, **kwargs)


def _status_code(error: Exception) -> int | None:
    """Return an HTTP status from a provider error, however it exposes one.

    ``httpx.HTTPStatusError`` carries the status on ``.response``, not on the
    exception, so reading only ``status_code`` would misclassify 429 and 5xx
    responses as generic provider errors and silently disable governed
    ``rate_limit``/``unavailable`` fallback.
    """
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    status = getattr(getattr(error, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def _mapping(value: object) -> dict[str, Any]:
    """Copy a mapping with string keys, or return an empty mapping."""
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _integer(value: object) -> int:
    """Return a non-negative integer from provider metadata."""
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _optional_string(value: object) -> str | None:
    """Return a non-empty string or ``None``."""
    return value if isinstance(value, str) and value else None


__all__ = ["LangChainModelProvider"]
