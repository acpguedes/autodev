"""Behavior tests for the provider-neutral model gateway."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Mapping

import pytest

from backend.llm import (
    EstimatedCost,
    ExecutionMetadata,
    MessageContent,
    ModelAuthenticationError,
    ModelBudgetExceededError,
    ModelCapabilities,
    ModelProviderNotConfiguredError,
    ModelRequest,
    ModelResponse,
    ModelUnavailableError,
    ModelUnsupportedCapabilityError,
    NormalizedMessage,
    StreamChunk,
    StructuredOutput,
    TokenUsage,
    ToolCall,
)
from backend.llm.gateway import ModelGateway
from backend.llm.model_config import ModelConfig, ModelLimits, ModelTarget
from backend.llm.registry import ModelProviderRegistry, resolve_model_config
from backend.llm.stub_provider import StubModelOutput, StubModelProvider


def _request(*, tools: bool = False, structured: bool = False) -> ModelRequest:
    """Build a small normalized request for gateway tests."""
    message = NormalizedMessage(
        role="user",
        content=(MessageContent(type="text", text="hello"),),
    )
    tool_calls = (
        ToolCall(id="call-1", name="read_file", arguments={"path": "README.md"}),
    )
    return ModelRequest(
        messages=(replace(message, tool_calls=tool_calls) if tools else message,),
        structured_output_schema={"type": "object"} if structured else None,
    )


def _metadata() -> ExecutionMetadata:
    """Build caller metadata without prompt or credential content."""
    return ExecutionMetadata(
        provider="gateway",
        model="unresolved",
        attributes={
            "agent_id": "acme/coder",
            "run_id": "run-1",
            "tenant_id": "tenant-1",
        },
    )


def test_resolver_uses_override_then_agent_then_global_without_inheriting_fallbacks() -> (
    None
):
    """Execution selection wins and only an omitted provider inherits from global."""
    global_config = ModelConfig(
        provider="stub",
        name="global",
        fallback_on=("timeout",),
        fallback=(ModelTarget(provider="stub", name="global-safe"),),
    )
    agent_config = ModelConfig(provider="openai", name="agent")
    override = ModelConfig(provider=None, name="override")

    resolved = resolve_model_config(
        execution_override=override,
        agent_config=agent_config,
        global_config=global_config,
    )

    assert resolved.provider == "stub"
    assert resolved.name == "override"
    assert resolved.fallback == ()
    assert (
        resolve_model_config(
            agent_config=agent_config, global_config=global_config
        ).name
        == "agent"
    )
    assert resolve_model_config(global_config=global_config).name == "global"


def test_preflight_rejects_any_unregistered_provider_before_first_invocation() -> None:
    """A missing fallback provider prevents a valid primary from being called."""
    primary = StubModelProvider(responses={"primary": "should-not-run"})
    gateway = ModelGateway(ModelProviderRegistry({"stub": primary}))
    config = ModelConfig(
        provider="stub",
        name="primary",
        fallback_on=("unavailable",),
        fallback=(ModelTarget(provider="missing", name="fallback"),),
    )

    with pytest.raises(ModelProviderNotConfiguredError) as raised:
        gateway.complete(_request(), config, metadata=_metadata())

    assert raised.value.code == "provider_not_configured"
    assert primary.calls == ()


def test_missing_capability_is_explicit_and_prevents_invocation() -> None:
    """Inferred tool capability is checked against provider declarations."""
    provider = StubModelProvider(
        responses={"primary": "should-not-run"},
        capabilities={"primary": ModelCapabilities(("text",))},
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))
    config = ModelConfig(
        provider="stub",
        name="primary",
        required_capabilities=("text", "tool_calling"),
    )

    with pytest.raises(ModelUnsupportedCapabilityError) as raised:
        gateway.complete(_request(), config, metadata=_metadata())

    assert getattr(raised.value, "code") == "unsupported_capability"
    assert provider.calls == ()


def test_capability_failure_routes_only_when_explicitly_configured() -> None:
    """An incompatible primary can route to a capable fallback only by policy."""
    provider = StubModelProvider(
        responses={"fallback": "done"},
        capabilities={
            "primary": ModelCapabilities(("text",)),
            "fallback": ModelCapabilities(("text", "tool_calling")),
        },
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))
    config = ModelConfig(
        provider="stub",
        name="primary",
        required_capabilities=("text", "tool_calling"),
        fallback_on=("unsupported_capability",),
        fallback=(ModelTarget(provider="stub", name="fallback"),),
    )

    response = gateway.complete(_request(), config, metadata=_metadata())

    assert response.message.content[0].text == "done"
    assert [call.target.name for call in provider.calls] == ["fallback"]
    assert [target.name for target in provider.capability_checks] == [
        "primary",
        "fallback",
    ]
    assert [attempt.error_code for attempt in gateway.attempts] == [
        "unsupported_capability",
        None,
    ]


def test_retries_then_ordered_fallback_happen_only_for_configured_errors() -> None:
    """Configured transient failures retry the target before ordered fallback."""
    provider = StubModelProvider(
        responses={
            "primary": (
                ModelUnavailableError("down"),
                ModelUnavailableError("still down"),
            ),
            "safe-one": ModelUnavailableError("fallback down"),
            "safe-two": StubModelOutput(text="safe"),
        }
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))
    config = ModelConfig(
        provider="stub",
        name="primary",
        retries=1,
        fallback_on=("unavailable",),
        fallback=(
            ModelTarget(provider="stub", name="safe-one", retries=0),
            ModelTarget(provider="stub", name="safe-two", retries=0),
        ),
    )

    response = gateway.complete(_request(), config, metadata=_metadata())

    assert response.message.content[0].text == "safe"
    assert [call.target.name for call in provider.calls] == [
        "primary",
        "primary",
        "safe-one",
        "safe-two",
    ]
    assert [attempt.attempt for attempt in gateway.attempts] == [1, 2, 3, 4]


def test_unconfigured_error_neither_retries_nor_falls_back_and_is_redacted() -> None:
    """An authentication failure bypasses timeout-only recovery without leaking secrets."""
    provider = StubModelProvider(
        responses={
            "primary": ModelAuthenticationError(
                "OPENAI_API_KEY=sk-super-secret Bearer token-value rejected"
            ),
            "fallback": "should-not-run",
        }
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))
    config = ModelConfig(
        provider="stub",
        name="primary",
        retries=2,
        fallback_on=("timeout",),
        fallback=(ModelTarget(provider="stub", name="fallback"),),
    )

    with pytest.raises(ModelAuthenticationError) as raised:
        gateway.complete(_request(), config, metadata=_metadata())

    assert "super-secret" not in str(raised.value)
    assert "token-value" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
    assert [call.target.name for call in provider.calls] == ["primary"]
    assert gateway.attempts[0].error_code == "authentication"


@pytest.mark.parametrize(
    ("limits", "output"),
    [
        (
            ModelLimits(max_total_tokens=4),
            StubModelOutput(text="x", usage=TokenUsage(3, 2)),
        ),
        (
            ModelLimits(max_cost_usd=0.5),
            StubModelOutput(text="x", cost=EstimatedCost(0.75)),
        ),
    ],
)
def test_token_and_cost_limits_fail_closed(
    limits: ModelLimits,
    output: StubModelOutput,
) -> None:
    """A completed provider response is withheld when aggregate limits are exceeded."""
    provider = StubModelProvider(responses={"primary": output})
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))

    with pytest.raises(ModelBudgetExceededError):
        gateway.complete(
            _request(),
            ModelConfig(provider="stub", name="primary", limits=limits),
            metadata=_metadata(),
        )

    assert len(provider.calls) == 1
    assert gateway.attempts[0].error_code == "budget_exceeded"
    assert gateway.attempts[0].usage == output.usage
    assert gateway.attempts[0].cost == output.cost


def test_call_limit_blocks_fallback_before_an_extra_provider_call() -> None:
    """Call budgets include failed attempts and stop before the next target."""
    provider = StubModelProvider(
        responses={"primary": ModelUnavailableError("down"), "fallback": "no"}
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))
    config = ModelConfig(
        provider="stub",
        name="primary",
        fallback_on=("unavailable",),
        limits=ModelLimits(max_calls=1),
        fallback=(ModelTarget(provider="stub", name="fallback"),),
    )

    with pytest.raises(ModelBudgetExceededError):
        gateway.complete(_request(), config, metadata=_metadata())

    assert [call.target.name for call in provider.calls] == ["primary"]


def test_stream_normalizes_chunks_and_enforces_streaming_capability() -> None:
    """Gateway streaming returns ordered internal chunks from an offline provider."""
    provider = StubModelProvider(
        streams={
            "streamer": (
                StreamChunk(index=0, content_delta="hel"),
                StreamChunk(
                    index=1, content_delta="lo", usage=TokenUsage(1, 1), done=True
                ),
            )
        }
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))
    config = ModelConfig(provider="stub", name="streamer")

    chunks = tuple(gateway.stream(_request(), config, metadata=_metadata()))

    assert [chunk.content_delta for chunk in chunks] == ["hel", "lo"]
    assert chunks[-1].done is True
    assert provider.calls[0].stream is True


def test_stream_yields_live_without_buffering_the_whole_provider_attempt() -> None:
    """The first normalized chunk reaches callers before the provider produces the second."""
    events: list[str] = []

    class LiveProvider:
        def capabilities(self, target: ModelTarget) -> ModelCapabilities:
            return ModelCapabilities(("text", "streaming"))

        def complete(
            self,
            request: ModelRequest,
            target: ModelTarget,
            metadata: ExecutionMetadata,
        ) -> ModelResponse:
            raise AssertionError("complete must not be called")

        def stream(
            self,
            request: ModelRequest,
            target: ModelTarget,
            metadata: ExecutionMetadata,
        ) -> Iterable[StreamChunk]:
            def chunks() -> Iterable[StreamChunk]:
                events.append("first")
                yield StreamChunk(index=0, content_delta="a")
                events.append("second")
                yield StreamChunk(index=1, content_delta="b", done=True)

            return chunks()

    gateway = ModelGateway(ModelProviderRegistry({"live": LiveProvider()}))
    stream = iter(
        gateway.stream(
            _request(),
            ModelConfig(provider="live", name="model"),
            metadata=_metadata(),
        )
    )

    assert next(stream).content_delta == "a"
    assert events == ["first"]
    assert [chunk.content_delta for chunk in stream] == ["b"]
    assert events == ["first", "second"]


def test_stub_normalizes_all_response_fields_without_network_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stub output becomes a complete internal response and never opens a socket."""

    def fail_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr("socket.create_connection", fail_network)
    output = StubModelOutput(
        text="done",
        tool_calls=(
            ToolCall(id="call-1", name="read_file", arguments={"path": "a.py"}),
        ),
        structured_output=StructuredOutput({"ok": True}, schema_name="result"),
        usage=TokenUsage(input_tokens=4, output_tokens=2),
        cost=EstimatedCost(usd=0.01),
        finish_reason="tool_calls",
    )
    provider = StubModelProvider(responses={"model-a": output})
    target = ModelTarget(provider="stub", name="model-a")

    response = provider.complete(_request(), target, _metadata())

    assert response.message.content[0].text == "done"
    assert response.message.tool_calls[0].name == "read_file"
    assert response.structured_output is not None
    assert isinstance(response.structured_output.value, Mapping)
    assert response.structured_output.value["ok"] is True
    assert response.usage.total_tokens == 6
    assert response.cost.usd == 0.01
    assert response.metadata.finish_reason == "tool_calls"
