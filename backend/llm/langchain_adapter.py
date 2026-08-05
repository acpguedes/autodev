"""Replaceable LangChain adapter contained behind AutoDev model contracts."""

from __future__ import annotations

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
            raise _normalize_exception(exc, target) from exc

    def stream(
        self,
        request: ModelRequest,
        target: ModelTarget,
        metadata: ExecutionMetadata,
    ) -> Iterable[StreamChunk]:
        """Stream LangChain chunks normalized to the internal chunk contract."""
        try:
            model = self._model(target)
            runnable = cast(_Runnable, _bind_tools(model, request))
            iterator = iter(runnable.stream(_langchain_messages(request)))
            current = next(iterator, None)
            index = 0
            while current is not None:
                following = next(iterator, None)
                yield _normalize_chunk(current, index=index, done=following is None)
                current = following
                index += 1
        except Exception as exc:
            raise _normalize_exception(exc, target) from exc

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


def _structured_runnable(model: object, request: ModelRequest) -> object:
    """Select LangChain's native provider structured-output mode."""
    structured = getattr(model, "with_structured_output", None)
    if not callable(structured) or request.structured_output_schema is None:
        raise ModelInvalidRequestError(
            "configured model does not support native structured output"
        )
    tools = _tool_definitions(request)
    kwargs: dict[str, object] = {"include_raw": True}
    if tools:
        kwargs.update({"tools": tools, "strict": True})
    return structured(dict(request.structured_output_schema), **kwargs)


def _native_structured_response(
    native: object,
) -> tuple[object, StructuredOutput | None]:
    """Consume LangChain's include-raw native structured result."""
    result = _mapping(native)
    raw = result.get("raw")
    if raw is None:
        raise ModelInvalidRequestError(
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


def _normalize_chunk(raw: object, *, index: int, done: bool) -> StreamChunk:
    """Translate one LangChain streaming chunk."""
    content = getattr(raw, "content", "")
    text = content if isinstance(content, str) else json.dumps(content, sort_keys=True)
    metadata = _mapping(getattr(raw, "response_metadata", {}))
    return StreamChunk(
        index=index,
        content_delta=text,
        tool_calls=_tool_calls(getattr(raw, "tool_calls", ())),
        usage=_usage(raw, metadata),
        cost=_estimated_cost(raw, metadata),
        done=done,
    )


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
    status = getattr(error, "status_code", None)
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
