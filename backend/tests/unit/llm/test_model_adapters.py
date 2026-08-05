"""Tests for legacy and LangChain model-provider adapters."""

from __future__ import annotations

import types

import pytest

from backend.agents.provider import (
    LLMProviderResponse,
    StubLLMProvider,
    as_model_provider,
)
from backend.llm import (
    EstimatedCost,
    ExecutionMetadata,
    MessageContent,
    ModelAuthenticationError,
    ModelInvalidRequestError,
    ModelRequest,
    ModelUnsupportedCapabilityError,
    NormalizedMessage,
    TokenUsage,
    ToolDefinition,
)
from backend.llm.langchain_adapter import LangChainModelProvider
from backend.llm.model_config import ModelTarget


def _request(*, tools: bool = True, structured: bool = False) -> ModelRequest:
    """Build a request containing text and a tool definition."""
    return ModelRequest(
        messages=(
            NormalizedMessage(
                role="user",
                content=(MessageContent(type="text", text="hello"),),
            ),
        ),
        tools=(
            (
                ToolDefinition(
                    name="read_file",
                    description="Read a file.",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                ),
            )
            if tools
            else ()
        ),
        structured_output_schema={"type": "object"} if structured else None,
    )


def _metadata() -> ExecutionMetadata:
    """Build execution metadata used by adapter calls."""
    return ExecutionMetadata(
        provider="stub",
        model="model-a",
        attributes={"agent_id": "agent-a", "run_id": "run-a", "tenant_id": "tenant-a"},
    )


def test_legacy_adapter_preserves_existing_provider_contract() -> None:
    """Existing text-only providers remain usable behind the internal gateway seam."""
    legacy = StubLLMProvider(
        text="legacy", tokens_input=3, tokens_output=2, cost_usd=0.4
    )
    adapter = as_model_provider(legacy)

    response = adapter.complete(
        _request(tools=False),
        ModelTarget(provider="legacy", name="legacy-model"),
        _metadata(),
    )

    assert response.message.content[0].text == "legacy"
    assert response.usage == TokenUsage(input_tokens=3, output_tokens=2)
    assert response.cost.usd == 0.4


def test_langchain_adapter_normalizes_message_usage_tools_and_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LangChain response objects are contained and translated at the adapter boundary."""
    calls: list[dict[str, object]] = []

    class FakeBoundModel:
        def invoke(self, messages: object) -> object:
            calls.append({"messages": messages})
            return types.SimpleNamespace(
                content="not-json",
                tool_calls=[
                    {"id": "call-1", "name": "read_file", "args": {"path": "a.py"}}
                ],
                usage_metadata={"input_tokens": 5, "output_tokens": 2},
                response_metadata={
                    "finish_reason": "tool_calls",
                    "request_id": "req-1",
                },
            )

    class FakeStructuredModel:
        def invoke(self, messages: object) -> object:
            calls.append({"structured_messages": messages})
            raw = FakeBoundModel().invoke(messages)
            return {"raw": raw, "parsed": {"ok": True}, "parsing_error": None}

    class FakeModel:
        def bind_tools(self, tools: object) -> FakeBoundModel:
            calls.append({"tools": tools})
            return FakeBoundModel()

        def with_structured_output(
            self, schema: object, **kwargs: object
        ) -> FakeStructuredModel:
            calls.append({"structured_schema": schema, "structured_kwargs": kwargs})
            return FakeStructuredModel()

    factory_calls: list[dict[str, object]] = []

    def fake_factory(**kwargs: object) -> FakeModel:
        factory_calls.append(kwargs)
        return FakeModel()

    monkeypatch.setattr("backend.llm.langchain_adapter.get_chat_model", fake_factory)
    adapter = LangChainModelProvider("openai")
    target = ModelTarget(
        provider="openai",
        name="gpt-test",
        temperature=0.1,
        max_tokens=256,
        timeout_seconds=4,
    )

    response = adapter.complete(_request(structured=True), target, _metadata())

    assert factory_calls == [
        {
            "provider": "openai",
            "model": "gpt-test",
            "temperature": 0.1,
            "max_tokens": 256,
            "request_timeout": 4,
            "allow_stub": False,
        }
    ]
    assert response.message.content[0].text == "not-json"
    assert response.message.tool_calls[0].arguments["path"] == "a.py"
    assert response.usage.total_tokens == 7
    assert response.metadata.finish_reason == "tool_calls"
    assert response.metadata.request_id == "req-1"
    assert response.structured_output is not None
    assert response.structured_output.value == {"ok": True}
    assert calls[0]["structured_schema"] == {"type": "object"}
    structured_kwargs = calls[0]["structured_kwargs"]
    assert isinstance(structured_kwargs, dict)
    assert structured_kwargs["include_raw"] is True
    assert structured_kwargs["tools"]


def _structured_adapter(
    monkeypatch: pytest.MonkeyPatch, model: object
) -> LangChainModelProvider:
    """Register a fake chat model behind the contained LangChain adapter."""
    monkeypatch.setattr(
        "backend.llm.langchain_adapter.get_chat_model", lambda **kwargs: model
    )
    return LangChainModelProvider("openai")


def _ai_message() -> object:
    """Build a minimal LangChain-shaped assistant message."""
    return types.SimpleNamespace(
        content="{}",
        tool_calls=[],
        usage_metadata={},
        response_metadata={},
    )


def test_structured_output_requires_native_provider_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model without native structured output fails as a capability error."""

    class NoStructuredModel:
        def bind_tools(self, tools: object) -> object:  # pragma: no cover - unused
            raise AssertionError("tool binding must not be reached")

    adapter = _structured_adapter(monkeypatch, NoStructuredModel())

    with pytest.raises(ModelUnsupportedCapabilityError):
        adapter.complete(
            _request(structured=True),
            ModelTarget(provider="openai", name="gpt-test"),
            _metadata(),
        )


def test_structured_output_requires_a_raw_capable_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Providers that cannot return the raw envelope fail closed, not silently."""

    class NoRawModel:
        def with_structured_output(
            self, schema: object, *, method: str = "json_schema"
        ) -> object:  # pragma: no cover - never invoked
            raise AssertionError("structured runnable must not be built")

    adapter = _structured_adapter(monkeypatch, NoRawModel())

    with pytest.raises(ModelUnsupportedCapabilityError):
        adapter.complete(
            _request(structured=True),
            ModelTarget(provider="openai", name="gpt-test"),
            _metadata(),
        )


def test_structured_output_never_silently_drops_requested_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool calling combined with structured output fails when unsupported."""

    class NoToolsStructuredModel:
        def with_structured_output(
            self, schema: object, *, include_raw: bool = False
        ) -> object:  # pragma: no cover - never invoked
            raise AssertionError("structured runnable must not be built")

    adapter = _structured_adapter(monkeypatch, NoToolsStructuredModel())

    with pytest.raises(ModelUnsupportedCapabilityError):
        adapter.complete(
            _request(tools=True, structured=True),
            ModelTarget(provider="openai", name="gpt-test"),
            _metadata(),
        )


def test_structured_output_without_tools_sends_only_portable_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``include_raw`` is forwarded when the request declares no tools."""
    seen: dict[str, object] = {}

    class StructuredRunnable:
        def invoke(self, messages: object) -> object:
            return {"raw": _ai_message(), "parsed": {"ok": True}, "parsing_error": None}

    class FakeModel:
        def with_structured_output(
            self, schema: object, *, include_raw: bool = False, tools: object = None
        ) -> object:
            seen.update({"include_raw": include_raw, "tools": tools})
            return StructuredRunnable()

    adapter = _structured_adapter(monkeypatch, FakeModel())

    response = adapter.complete(
        _request(tools=False, structured=True),
        ModelTarget(provider="openai", name="gpt-test"),
        _metadata(),
    )

    assert seen == {"include_raw": True, "tools": None}
    assert response.structured_output is not None
    assert response.structured_output.value == {"ok": True}


def test_structured_output_parsing_failure_is_an_invalid_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native parsing error is a bad model output, not a capability gap."""

    class StructuredRunnable:
        def invoke(self, messages: object) -> object:
            return {
                "raw": _ai_message(),
                "parsed": None,
                "parsing_error": ValueError("cannot parse"),
            }

    class FakeModel:
        def with_structured_output(self, schema: object, **kwargs: object) -> object:
            return StructuredRunnable()

    adapter = _structured_adapter(monkeypatch, FakeModel())

    with pytest.raises(ModelInvalidRequestError):
        adapter.complete(
            _request(tools=False, structured=True),
            ModelTarget(provider="openai", name="gpt-test"),
            _metadata(),
        )


def test_structured_output_requires_the_include_raw_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that ignores ``include_raw`` fails as a capability error."""

    class StructuredRunnable:
        def invoke(self, messages: object) -> object:
            return {"ok": True}

    class FakeModel:
        def with_structured_output(self, schema: object, **kwargs: object) -> object:
            return StructuredRunnable()

    adapter = _structured_adapter(monkeypatch, FakeModel())

    with pytest.raises(ModelUnsupportedCapabilityError):
        adapter.complete(
            _request(tools=False, structured=True),
            ModelTarget(provider="openai", name="gpt-test"),
            _metadata(),
        )


def test_langchain_missing_credentials_fail_closed_as_typed_redacted_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory configuration failures never produce a permissive stub fallback."""

    def failing_factory(**kwargs: object) -> object:
        raise RuntimeError("OPENAI_API_KEY=sk-live-secret is required")

    monkeypatch.setattr("backend.llm.langchain_adapter.get_chat_model", failing_factory)
    adapter = LangChainModelProvider("openai")

    with pytest.raises(ModelAuthenticationError) as raised:
        adapter.complete(
            _request(),
            ModelTarget(provider="openai", name="gpt-test"),
            _metadata(),
        )

    assert "live-secret" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)


def test_langchain_adapter_streams_only_normalized_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registered streaming support yields ordered internal chunks with final usage."""

    class FakeModel:
        def stream(self, messages: object) -> object:
            return iter(
                (
                    types.SimpleNamespace(
                        content="hel", tool_calls=[], usage_metadata={}
                    ),
                    types.SimpleNamespace(
                        content="lo",
                        tool_calls=[],
                        usage_metadata={
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "estimated_cost_usd": 0.02,
                        },
                    ),
                )
            )

    monkeypatch.setattr(
        "backend.llm.langchain_adapter.get_chat_model", lambda **kwargs: FakeModel()
    )
    adapter = LangChainModelProvider("ollama")

    chunks = tuple(
        adapter.stream(
            _request(tools=False),
            ModelTarget(provider="ollama", name="llama-test"),
            _metadata(),
        )
    )

    assert [chunk.content_delta for chunk in chunks] == ["hel", "lo", ""]
    assert chunks[0].usage is None
    assert chunks[0].done is False
    assert chunks[-1].usage == TokenUsage(1, 1)
    assert chunks[-1].cost == EstimatedCost(0.02)
    assert chunks[-1].done is True


def test_langchain_stream_yields_each_chunk_before_pulling_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter never prefetches a later chunk before delivering the current one."""
    produced: list[str] = []

    def provider_chunks() -> object:
        for text in ("a", "b"):
            produced.append(text)
            yield types.SimpleNamespace(content=text, tool_calls=[], usage_metadata={})

    class FakeModel:
        def stream(self, messages: object) -> object:
            return provider_chunks()

    monkeypatch.setattr(
        "backend.llm.langchain_adapter.get_chat_model", lambda **kwargs: FakeModel()
    )
    adapter = LangChainModelProvider("openai")

    stream = iter(
        adapter.stream(
            _request(tools=False),
            ModelTarget(provider="openai", name="gpt-test"),
            _metadata(),
        )
    )

    first = next(stream)

    assert first.content_delta == "a"
    assert produced == ["a"]
    assert [chunk.content_delta for chunk in stream] == ["b", ""]


def test_langchain_stream_reports_absent_cost_metadata_as_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Providers that report no cost yield ``None`` instead of a fabricated zero."""

    class FakeModel:
        def stream(self, messages: object) -> object:
            return iter(
                (
                    types.SimpleNamespace(
                        content="ok",
                        tool_calls=[],
                        usage_metadata={"input_tokens": 1, "output_tokens": 1},
                    ),
                )
            )

    monkeypatch.setattr(
        "backend.llm.langchain_adapter.get_chat_model", lambda **kwargs: FakeModel()
    )
    adapter = LangChainModelProvider("openai")

    chunks = tuple(
        adapter.stream(
            _request(tools=False),
            ModelTarget(provider="openai", name="gpt-test"),
            _metadata(),
        )
    )

    assert all(chunk.cost is None for chunk in chunks)
    assert chunks[-1].usage == TokenUsage(1, 1)


def test_langchain_stream_refuses_structured_output_instead_of_degrading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streaming cannot silently drop a requested structured-output schema."""

    class FakeModel:
        def stream(self, messages: object) -> object:  # pragma: no cover - unreachable
            raise AssertionError("provider must not be invoked")

    monkeypatch.setattr(
        "backend.llm.langchain_adapter.get_chat_model", lambda **kwargs: FakeModel()
    )
    adapter = LangChainModelProvider("openai")

    with pytest.raises(ModelUnsupportedCapabilityError):
        tuple(
            adapter.stream(
                _request(tools=False, structured=True),
                ModelTarget(provider="openai", name="gpt-test"),
                _metadata(),
            )
        )


def test_legacy_response_shape_remains_source_compatible() -> None:
    """Task 2 does not change the public legacy response constructor."""
    assert LLMProviderResponse("ok").text == "ok"
