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
from opentelemetry.trace import StatusCode
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from backend.llm import (
    EstimatedCost,
    ExecutionMetadata,
    ModelConfig,
    ModelRequest,
    ModelResponse,
    StreamChunk,
)
from backend.llm.gateway import ModelGateway
from backend.llm.model_config import ModelTarget
from backend.llm.registry import ModelProviderRegistry
from backend.llm.stub_provider import StubModelProvider
from backend.observability.tracing import (
    MODEL_ERROR_CODES,
    ModelCallTrace,
    configure_tracing,
    model_call_span_attributes,
    trace_model_call,
    trace_run_step,
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

    Driving this through the real gateway matters: the gateway assigns the code
    itself, so a test that only calls ``trace_model_call`` directly exercises
    the branch that was already safe and passes while the live path leaks.
    """

    class VendorError(Exception):
        code = "invalid_api_key"

    class FailingProvider(StubModelProvider):
        def complete(
            self,
            request: ModelRequest,
            target: ModelTarget,
            metadata: ExecutionMetadata,
        ) -> ModelResponse:
            raise VendorError(
                "401 Unauthorized: api_key=sk-livesecret1234567890 rejected"
            )

    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)
    gateway = ModelGateway(
        ModelProviderRegistry({"stub": FailingProvider(responses={"m": "x"})})
    )

    with pytest.raises(Exception):
        gateway.complete(
            ModelRequest(messages=()),
            ModelConfig(provider="stub", name="m"),
            metadata=ExecutionMetadata(provider="stub", model="m"),
        )

    spans = [s for s in exporter.get_finished_spans() if s.name == "autodev.model.call"]
    assert spans, "the failing attempt must still produce a span"
    for span in spans:
        code = (span.attributes or {})["autodev.model.error_code"]
        assert code in MODEL_ERROR_CODES
        assert code != "invalid_api_key"


def test_span_never_records_a_raw_provider_exception_message() -> None:
    """Credentials must not reach a span even though the caller message is redacted.

    OpenTelemetry's default ``record_exception`` attaches ``str(exc)`` verbatim,
    which happens before redaction runs on the caller-facing error object.
    """

    class LeakyError(Exception):
        code = "authentication"

    class FailingProvider(StubModelProvider):
        def complete(
            self,
            request: ModelRequest,
            target: ModelTarget,
            metadata: ExecutionMetadata,
        ) -> ModelResponse:
            raise LeakyError("api_key=sk-livesecret1234567890 rejected")

    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)
    gateway = ModelGateway(
        ModelProviderRegistry({"stub": FailingProvider(responses={"m": "x"})})
    )

    with pytest.raises(Exception) as raised:
        gateway.complete(
            ModelRequest(messages=()),
            ModelConfig(provider="stub", name="m"),
            metadata=ExecutionMetadata(provider="stub", model="m"),
        )

    assert "sk-livesecret" not in str(raised.value)
    for span in exporter.get_finished_spans():
        rendered = f"{span.attributes} {[(e.name, e.attributes) for e in span.events]}"
        assert "sk-livesecret" not in rendered


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


def test_no_span_or_log_carries_a_credential_through_the_exception_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Redaction must survive `raise ... from exc` and implicit context chaining.

    Disabling ``record_exception`` on the model span is not enough on its own:
    the raw provider exception stays reachable via ``__cause__``/``__context__``,
    OpenTelemetry formats exception chains, and every *other* span in the process
    (run steps, request middleware) still records exceptions by default. The same
    chain reaches ``logging`` whenever a handler logs with ``exc_info``.
    """
    secret = "sk-livesecret1234567890"

    class LeakyError(Exception):
        code = "authentication"

    class FailingProvider(StubModelProvider):
        def complete(
            self,
            request: ModelRequest,
            target: ModelTarget,
            metadata: ExecutionMetadata,
        ) -> ModelResponse:
            raise LeakyError(f"401 Unauthorized: api_key={secret} rejected")

    def failing_sink(telemetry: object) -> None:
        raise RuntimeError("sink down")

    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)
    gateway = ModelGateway(
        ModelProviderRegistry({"stub": FailingProvider(responses={"m": "x"})}),
        telemetry_sink=failing_sink,
    )

    with caplog.at_level("WARNING"):
        with pytest.raises(Exception) as raised:
            with trace_run_step(run_id="r", step_id="s", agent="a", status="running"):
                gateway.complete(
                    ModelRequest(messages=()),
                    ModelConfig(provider="stub", name="m"),
                    metadata=ExecutionMetadata(provider="stub", model="m"),
                )

    assert secret not in str(raised.value)
    assert secret not in caplog.text
    for span in exporter.get_finished_spans():
        rendered = f"{span.attributes} {[(e.name, e.attributes) for e in span.events]}"
        assert secret not in rendered, f"credential reached span {span.name}"


def test_break_after_the_terminal_chunk_leaves_a_clean_span() -> None:
    """The ordinary streaming idiom must not produce an ERROR span.

    ``GeneratorExit`` reaches the span context manager on every early exit,
    including ``break`` after ``chunk.done``. Treating it as a failure marked
    every successful stream as an error on the trace channel.
    """
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)
    provider = StubModelProvider(
        streams={
            "s": (
                StreamChunk(index=0, content_delta="a"),
                StreamChunk(index=1, done=True),
            )
        }
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))

    for chunk in gateway.stream(
        ModelRequest(messages=()),
        ModelConfig(provider="stub", name="s"),
        metadata=ExecutionMetadata(provider="stub", model="s"),
    ):
        if chunk.done:
            break

    spans = [s for s in exporter.get_finished_spans() if s.name == "autodev.model.call"]
    assert spans
    for span in spans:
        assert not (span.attributes or {}).get("autodev.model.error_code")
        assert span.status.status_code is not StatusCode.ERROR


def test_a_codeless_failure_is_visible_to_direct_tracer_users() -> None:
    """``trace_model_call`` is public, so its own fallback must mark the failure.

    Driving this through the gateway would not exercise it: the gateway assigns
    the code itself, so the tracer's fallback never runs on that path.
    """
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)

    with pytest.raises(RuntimeError):
        with trace_model_call(
            agent_id="a", provider="p", model="m", fallback_attempt=0
        ):
            raise RuntimeError("no code attribute")

    spans = [s for s in exporter.get_finished_spans() if s.name == "autodev.model.call"]
    assert spans
    assert (spans[-1].attributes or {})["autodev.model.error_code"] == "provider_error"
    assert spans[-1].status.status_code is StatusCode.ERROR


def test_a_codeless_provider_failure_is_still_visible_on_the_span() -> None:
    """An exception without its own ``code`` must not render as a clean span."""
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)

    class BareProvider(StubModelProvider):
        def complete(
            self,
            request: ModelRequest,
            target: ModelTarget,
            metadata: ExecutionMetadata,
        ) -> ModelResponse:
            raise RuntimeError("no code attribute")

    gateway = ModelGateway(
        ModelProviderRegistry({"stub": BareProvider(responses={"m": "x"})})
    )

    with pytest.raises(Exception):
        gateway.complete(
            ModelRequest(messages=()),
            ModelConfig(provider="stub", name="m"),
            metadata=ExecutionMetadata(provider="stub", model="m"),
        )

    spans = [s for s in exporter.get_finished_spans() if s.name == "autodev.model.call"]
    assert spans
    assert (spans[-1].attributes or {})["autodev.model.error_code"] == "provider_error"
    assert spans[-1].status.status_code is StatusCode.ERROR
