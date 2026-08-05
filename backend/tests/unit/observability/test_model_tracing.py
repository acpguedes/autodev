"""Tests for safe model-call OpenTelemetry attributes."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, get_args

import pytest
from opentelemetry import trace

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
from backend.observability.tracing import (
    MODEL_ERROR_CODES,
    ModelCallTrace,
    model_call_span_attributes,
    trace_model_call,
)


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

    monkeypatch.setattr("backend.observability.tracing.trace_model_call", capture_trace)
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


def test_observability_imports_cleanly_before_the_model_gateway() -> None:
    """Importing observability first must not hit a partially initialized module.

    ``backend.observability.tracing`` reaches ``backend.config`` and therefore
    ``backend.llm``. If the gateway imports the tracer at module scope the cycle
    closes, and any entrypoint whose first backend import is observability dies
    at startup. The test suite cannot catch that on its own because conftest
    always imports the app first.
    """
    repo_root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.observability.tracing import trace_model_call",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr


def test_span_error_code_never_escapes_the_gateway_taxonomy() -> None:
    """A provider's own error code must not leak onto the span.

    Provider SDK exceptions carry vendor codes such as ``invalid_api_key``.
    Recording those verbatim makes dashboards keyed on the stable vocabulary
    silently miss attempts.
    """

    class VendorError(Exception):
        code = "invalid_api_key"

    measurements: ModelCallTrace | None = None
    with pytest.raises(VendorError):
        with trace_model_call(
            agent_id="a", provider="openai", model="m", fallback_attempt=0
        ) as trace:
            measurements = trace
            raise VendorError("vendor specific")

    assert measurements is not None
    assert measurements.error_code == "provider_error"
    assert measurements.error_code in MODEL_ERROR_CODES


def test_taxonomy_error_codes_match_the_contract_vocabulary() -> None:
    """The duplicated observability vocabulary must not drift from the contract."""
    from backend.llm.contracts import ModelErrorCode

    assert MODEL_ERROR_CODES == set(get_args(ModelErrorCode))


def test_streaming_span_does_not_reparent_caller_work() -> None:
    """A suspended stream must not capture unrelated caller spans as children."""
    provider = StubModelProvider(
        streams={
            "m": (
                StreamChunk(index=0, content_delta="a"),
                StreamChunk(index=1, done=True),
            )
        }
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))

    stream = iter(
        gateway.stream(
            ModelRequest(messages=()),
            ModelConfig(provider="stub", name="m"),
            metadata=ExecutionMetadata(provider="stub", model="m"),
        )
    )
    next(stream)
    current = trace.get_current_span().get_span_context()
    tuple(stream)

    assert not current.is_valid, "model span must not stay current across a yield"
