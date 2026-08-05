"""Contract tests for the provider-neutral model gateway surface."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Mapping

import pytest

from backend.llm.contracts import (
    AttemptTelemetry,
    EstimatedCost,
    ExecutionMetadata,
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


class _ConformingProvider:
    """Small real implementation used to exercise the structural protocol."""

    def complete(self, request: ModelRequest) -> ModelResponse:
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
    response = provider.complete(request)

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
    chunk = StreamChunk(index=0, content_delta="partial", done=False)
    telemetry = AttemptTelemetry(
        attempt=1,
        provider="stub",
        model="coder-primary",
        duration_ms=12.5,
        error_code="timeout",
    )
    structured = StructuredOutput(value={"status": "ok"}, schema_name="result")
    error = ModelTimeoutError("provider timed out", provider="stub", model="coder-primary")

    assert capabilities.supports("text") is True
    assert chunk.content_delta == "partial"
    assert telemetry.error_code == "timeout"
    assert isinstance(structured.value, Mapping)
    assert structured.value["status"] == "ok"
    assert error.code == "timeout"
    assert error.retryable is True
