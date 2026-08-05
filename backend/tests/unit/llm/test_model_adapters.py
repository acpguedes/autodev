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
    ExecutionMetadata,
    MessageContent,
    ModelAuthenticationError,
    ModelRequest,
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
                content='{"ok": true}',
                tool_calls=[
                    {"id": "call-1", "name": "read_file", "args": {"path": "a.py"}}
                ],
                usage_metadata={"input_tokens": 5, "output_tokens": 2},
                response_metadata={
                    "finish_reason": "tool_calls",
                    "request_id": "req-1",
                },
            )

    class FakeModel:
        def bind_tools(self, tools: object) -> FakeBoundModel:
            calls.append({"tools": tools})
            return FakeBoundModel()

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
    assert response.message.content[0].text == '{"ok": true}'
    assert response.message.tool_calls[0].arguments["path"] == "a.py"
    assert response.usage.total_tokens == 7
    assert response.metadata.finish_reason == "tool_calls"
    assert response.metadata.request_id == "req-1"
    assert response.structured_output is not None
    assert response.structured_output.value == {"ok": True}
    assert "tools" in calls[0]


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
                        usage_metadata={"input_tokens": 1, "output_tokens": 1},
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

    assert [chunk.content_delta for chunk in chunks] == ["hel", "lo"]
    assert chunks[-1].usage == TokenUsage(1, 1)
    assert chunks[-1].done is True


def test_legacy_response_shape_remains_source_compatible() -> None:
    """Task 2 does not change the public legacy response constructor."""
    assert LLMProviderResponse("ok").text == "ok"
