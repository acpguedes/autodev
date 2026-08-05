"""Contract tests for the provider-neutral model gateway surface."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Mapping

import pytest

from backend.llm.contracts import (
    AttemptTelemetry,
    EstimatedCost,
    ExecutionMetadata,
    MODEL_CAPABILITY_IDS,
    MODEL_ERROR_CODES,
    MessageContent,
    ModelCapabilities,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelTimeoutError,
    NormalizedMessage,
    StreamChunk,
    StructuredOutput,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from backend.llm.model_config import ModelTarget


def _agent_schema() -> dict[str, object]:
    """Load the published agent manifest schema consumed by plugin tooling."""
    schema_path = Path(__file__).parents[2] / "agents" / "schemas" / "agent.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


class _ConformingProvider:
    """Small real implementation used to exercise the structural protocol."""

    def capabilities(self, target: ModelTarget) -> ModelCapabilities:
        """Advertise the target's text capability."""
        return ModelCapabilities(("text",))

    def complete(
        self,
        request: ModelRequest,
        target: ModelTarget,
        metadata: ExecutionMetadata,
    ) -> ModelResponse:
        """Return a deterministic response for a provider-neutral request."""
        return ModelResponse(
            message=NormalizedMessage(
                role="assistant",
                content=(MessageContent(type="text", text="done"),),
            ),
            usage=TokenUsage(input_tokens=2, output_tokens=1),
            cost=EstimatedCost(usd=0.001),
            metadata=ExecutionMetadata(provider="stub", model="coder-primary"),
        )


def test_provider_contract_carries_normalized_messages_tools_and_usage() -> None:
    """A provider can consume and return the complete neutral contract without SDK types."""
    request = ModelRequest(
        messages=(
            NormalizedMessage(
                role="user",
                content=(MessageContent(type="text", text="Fix the test"),),
            ),
        ),
        tools=(
            ToolDefinition(
                name="read_file",
                description="Read one repository file.",
                input_schema={"type": "object", "required": ["path"]},
            ),
        ),
    )

    provider: ModelProvider = _ConformingProvider()
    response = provider.complete(
        request,
        ModelTarget(provider="stub", name="coder-primary"),
        ExecutionMetadata(provider="stub", model="coder-primary"),
    )

    assert response.message.content[0].text == "done"
    assert response.usage.total_tokens == 3
    assert response.cost.usd == 0.001
    assert request.tools[0].input_schema["required"] == ("path",)


def test_contracts_are_immutable_including_nested_json_values() -> None:
    """Frozen contracts prevent both attribute and nested JSON-like mutation."""
    call = ToolCall(id="call-1", name="read_file", arguments={"path": ["README.md"]})

    with pytest.raises(FrozenInstanceError):
        call.name = "write_file"  # type: ignore[misc]
    with pytest.raises(TypeError):
        call.arguments["path"] = ("AGENTS.md",)  # type: ignore[index]

    assert call.arguments["path"] == ("README.md",)


def test_contracts_copy_mutable_sequences_at_the_boundary() -> None:
    """Caller-owned lists cannot mutate a normalized request after construction."""
    content = [MessageContent(type="text", text="first")]
    tool_calls = [ToolCall(id="call-1", name="read_file")]
    message = NormalizedMessage(
        role="user",
        content=content,  # type: ignore[arg-type]
        tool_calls=tool_calls,  # type: ignore[arg-type]
    )
    messages = [message]
    tools = [ToolDefinition(name="read_file", description="Read", input_schema={})]
    request = ModelRequest(messages=messages, tools=tools)  # type: ignore[arg-type]
    chunk_calls = [ToolCall(id="call-2", name="read_file")]
    chunk = StreamChunk(index=0, tool_calls=chunk_calls)  # type: ignore[arg-type]
    supported = ["text"]
    capabilities = ModelCapabilities(supported=supported)  # type: ignore[arg-type]

    content.append(MessageContent(type="text", text="second"))
    tool_calls.clear()
    messages.clear()
    tools.clear()
    chunk_calls.clear()
    supported.clear()

    assert len(message.content) == 1
    assert len(message.tool_calls) == 1
    assert len(request.messages) == 1
    assert len(request.tools) == 1
    assert len(chunk.tool_calls) == 1
    assert capabilities.supports("text") is True


def test_stream_telemetry_capabilities_and_typed_errors_use_stable_ids() -> None:
    """Streaming, telemetry, capability, and error types expose stable neutral identifiers."""
    capabilities = ModelCapabilities(supported=("text",))
    chunk = StreamChunk(
        index=0,
        content_delta="partial",
        cost=EstimatedCost(usd=0.02),
        done=False,
    )
    telemetry = AttemptTelemetry(
        attempt=1,
        provider="stub",
        model="coder-primary",
        duration_ms=12.5,
        error_code="timeout",
    )
    structured = StructuredOutput(value={"status": "ok"}, schema_name="result")
    error = ModelTimeoutError(
        "provider timed out", provider="stub", model="coder-primary"
    )

    assert capabilities.supports("text") is True
    assert chunk.content_delta == "partial"
    assert chunk.cost == EstimatedCost(usd=0.02)
    assert telemetry.error_code == "timeout"
    assert isinstance(structured.value, Mapping)
    assert structured.value["status"] == "ok"
    assert error.code == "timeout"
    assert error.retryable is True


def test_capability_vocabulary_uses_tool_calling_and_matches_the_schema() -> None:
    """The public contract and manifest schema expose the exact capability vocabulary."""
    expected = frozenset({"text", "tool_calling", "structured_output", "streaming"})
    schema = _agent_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    model = properties["model"]
    assert isinstance(model, dict)
    model_properties = model["properties"]
    assert isinstance(model_properties, dict)
    required_capabilities = model_properties["requiredCapabilities"]
    assert isinstance(required_capabilities, dict)
    items = required_capabilities["items"]
    assert isinstance(items, dict)

    assert MODEL_CAPABILITY_IDS == expected
    assert frozenset(items["enum"]) == expected


def test_error_taxonomy_is_complete_and_matches_the_schema() -> None:
    """All normalized model failures are available to telemetry, fallback, and manifests."""
    expected = frozenset(
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
    schema = _agent_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    model = properties["model"]
    assert isinstance(model, dict)
    model_properties = model["properties"]
    assert isinstance(model_properties, dict)
    fallback_on = model_properties["fallbackOn"]
    assert isinstance(fallback_on, dict)
    items = fallback_on["items"]
    assert isinstance(items, dict)

    assert MODEL_ERROR_CODES == expected
    assert frozenset(items["enum"]) == expected
