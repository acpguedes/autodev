"""End-to-end correlation across HTTP, agent, model, event, log, and metrics."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.trace import SpanKind

from backend.agents.manifest import AgentManifest, validate_agent_manifest
from backend.agents.runtime import AgentRuntime, AgentRuntimeContext
from backend.events.bus import InMemoryEventBus
from backend.events.runtime import emit_event
from backend.llm import EstimatedCost, TokenUsage
from backend.llm.gateway import ModelGateway
from backend.llm.model_config import ModelConfig
from backend.llm.registry import ModelProviderRegistry
from backend.llm.stub_provider import StubModelOutput, StubModelProvider
from backend.observability.middleware import RequestTracingMiddleware
from backend.tests.observability_helpers import capture_observability


def _manifest() -> AgentManifest:
    """Build the real agent contract exercised by the integration request."""
    result = validate_agent_manifest(
        {
            "schemaVersion": "2.0",
            "kind": "Agent",
            "id": "autodev/integration-agent",
            "version": "1.0.0",
            "hostApi": ">=2.0 <3.0",
            "capabilities": [{"id": "code.implementation", "version": "1.0.0"}],
            "io": {
                "contract": "autodev/integration-io",
                "contractVersion": "1.0.0",
                "input": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["schemaVersion"],
                    "properties": {"schemaVersion": {"const": "1.0.0"}},
                },
                "output": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["schemaVersion", "result"],
                    "properties": {
                        "schemaVersion": {"const": "1.0.0"},
                        "result": {"type": "string"},
                    },
                },
            },
            "policy": {},
            "budgets": {},
            "entrypoint": {
                "runtime": "python",
                "ref": "integration_agent:Agent",
            },
        }
    )
    assert result.valid, result.errors
    assert result.manifest is not None
    return result.manifest


def _metric_points(capture: Any, name: str) -> list[Any]:
    """Return data points for one captured metric instrument.

    Args:
        capture: Active observability test capture.
        name: Exact OpenTelemetry instrument name.

    Returns:
        All matching data points.
    """
    data = capture.metric_reader.get_metrics_data()
    assert data is not None
    return [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def test_request_correlates_all_operational_signals_without_content() -> None:
    """One incoming W3C trace correlates every signal without prompt leakage."""
    secret_prompt = "sk-sensitive-prompt"
    incoming_trace_id = "0af7651916cd43dd8448eb211c80319c"
    incoming_parent_span_id = int("b7ad6b7169203331", 16)
    provider = StubModelProvider(
        responses={
            "m": StubModelOutput(
                text="done",
                usage=TokenUsage(4, 6),
                cost=EstimatedCost(0.5),
            )
        }
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))
    runtime = AgentRuntime(
        gateway=gateway,
        model_config=ModelConfig(provider="stub", name="m"),
    )
    event_bus = InMemoryEventBus()
    app = FastAPI()
    app.add_middleware(RequestTracingMiddleware)

    @app.post("/execute")
    async def execute() -> dict[str, str]:
        """Execute the real agent path within the active server span."""
        result = runtime.run(
            _manifest(),
            {"schemaVersion": "1.0.0"},
            lambda ctx: _call_model(ctx, secret_prompt),
            run_id="run-1",
            tenant_id="tenant-1",
        )
        emit_event(
            "flow.run.completed",
            tenant_id="tenant-1",
            partition_key="run-1",
            data={"status": result.status, "costUsd": 0.5, "tokens": 10},
            subject={"runId": "run-1"},
            bus=event_bus,
        )
        logging.getLogger("backend.integration").info(
            "agent execution completed",
            extra={"event": "agent.run.completed", "status": result.status},
        )
        return {"status": result.status}

    with capture_observability() as capture:
        response = TestClient(app).post(
            "/execute",
            headers={
                "traceparent": (
                    f"00-{incoming_trace_id}-{incoming_parent_span_id:016x}-01"
                )
            },
        )
        model_duration_points = _metric_points(
            capture, "gen_ai.client.operation.duration"
        )

    assert response.status_code == 200
    spans = capture.span_exporter.get_finished_spans()
    server_span = next(span for span in spans if span.kind is SpanKind.SERVER)
    agent_span = next(span for span in spans if span.name == "autodev.agent.run")
    step_span = next(
        span for span in spans if span.name == "autodev.run.step.run-handler"
    )
    model_span = next(span for span in spans if span.name == "autodev.model.call")
    event = event_bus.replay("run-1")[0]
    log_record = next(
        record
        for record in capture.log_exporter.get_finished_logs()
        if record.log_record.body == "agent execution completed"
    )

    assert server_span.parent is not None
    assert server_span.parent.span_id == incoming_parent_span_id
    assert agent_span.parent is not None
    assert agent_span.parent.span_id == server_span.context.span_id
    assert step_span.parent is not None
    assert step_span.parent.span_id == agent_span.context.span_id
    assert model_span.parent is not None
    assert model_span.parent.span_id in {
        step_span.context.span_id,
        agent_span.context.span_id,
    }
    assert event.traceId == f"{server_span.context.trace_id:032x}"
    assert log_record.log_record.trace_id == server_span.context.trace_id
    assert any(point.exemplars for point in model_duration_points)
    assert all(
        exemplar.trace_id == server_span.context.trace_id
        for point in model_duration_points
        for exemplar in point.exemplars
    )
    all_signals = (
        spans,
        capture.log_exporter.get_finished_logs(),
        model_duration_points,
        event,
    )
    assert secret_prompt not in repr(all_signals)


def _call_model(ctx: AgentRuntimeContext, prompt: str) -> dict[str, str]:
    """Call the gateway through the agent context and return typed output.

    Args:
        ctx: Active agent runtime context.
        prompt: Sensitive prompt used to verify telemetry exclusion.

    Returns:
        Contract-valid agent output.
    """
    return {"schemaVersion": "1.0.0", "result": ctx.call_llm(prompt)}
