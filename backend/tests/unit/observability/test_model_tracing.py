"""Tests for safe model-call OpenTelemetry attributes."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pytest

from backend.llm import (
    EstimatedCost,
    ExecutionMetadata,
    ModelConfig,
    ModelRequest,
    StreamChunk,
)
from backend.llm.gateway import ModelGateway
from backend.llm.registry import ModelProviderRegistry
from backend.llm.stub_provider import StubModelProvider
from backend.observability.tracing import ModelCallTrace, model_call_span_attributes


def test_model_call_attributes_include_governance_fields_and_exclude_content() -> None:
    """Model spans expose operational dimensions without prompts or credentials."""
    attributes = model_call_span_attributes(
        agent_id="acme/coder",
        provider="openai",
        model="gpt-test",
        latency_ms=12.5,
        input_tokens=4,
        output_tokens=2,
        estimated_cost_usd=0.01,
        error_code="timeout",
        fallback_attempt=2,
    )

    assert attributes == {
        "autodev.model.agent_id": "acme/coder",
        "autodev.model.provider": "openai",
        "autodev.model.name": "gpt-test",
        "autodev.model.latency_ms": 12.5,
        "autodev.model.tokens.input": 4,
        "autodev.model.tokens.output": 2,
        "autodev.model.estimated_cost_usd": 0.01,
        "autodev.model.error_code": "timeout",
        "autodev.model.fallback_attempt": 2,
    }
    assert all("prompt" not in key and "secret" not in key for key in attributes)


def test_streaming_cost_reaches_the_model_call_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gateway streaming copies the provider cost snapshot into its active span."""
    traces: list[ModelCallTrace] = []

    @contextmanager
    def capture_trace(**kwargs: object) -> Iterator[ModelCallTrace]:
        measurements = ModelCallTrace()
        yield measurements
        traces.append(measurements)

    monkeypatch.setattr("backend.llm.gateway.trace_model_call", capture_trace)
    provider = StubModelProvider(
        streams={
            "model": (
                StreamChunk(
                    index=0, content_delta="ok", cost=EstimatedCost(0.4), done=True
                ),
            )
        }
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))

    tuple(
        gateway.stream(
            ModelRequest(messages=()),
            ModelConfig(provider="stub", name="model"),
            metadata=ExecutionMetadata(provider="stub", model="model"),
        )
    )

    assert traces[0].estimated_cost_usd == 0.4
