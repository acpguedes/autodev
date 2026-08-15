"""Tests for the owned OpenTelemetry runtime and correlation context."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.api import main as api_main
from backend.config.settings import Settings
from backend.observability.context import (
    attach_execution_context,
    bind_correlation_context,
    capture_execution_context,
    current_correlation_context,
    current_span_id,
    current_trace_id,
    sanitize_identifier,
)
from backend.observability.metrics import NoopMetricSink, QueueSnapshot
from backend.observability.runtime import configure_observability
from backend.observability.tracing import get_tracer
from backend.tests.observability_helpers import capture_observability


def test_lifespan_shuts_down_observability_when_startup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A startup failure still closes the owned observability runtime."""
    events: list[str] = []
    monkeypatch.setattr(api_main, "get_settings", Settings)
    monkeypatch.setattr(
        api_main,
        "configure_observability",
        lambda settings: events.append(f"configured:{settings.autodev_profile}"),
    )
    monkeypatch.setattr(
        api_main,
        "get_runtime_config_service",
        lambda: SimpleNamespace(
            apply_to_environment=lambda: events.append("runtime-configured")
        ),
    )

    def fail_startup() -> None:
        """Represent a dependent service failing after telemetry starts."""
        events.append("startup-failed")
        raise RuntimeError("startup failed")

    monkeypatch.setattr(api_main, "get_orchestrator", fail_startup)
    monkeypatch.setattr(
        api_main,
        "shutdown_observability",
        lambda: events.append("observability-stopped"),
    )

    async def exercise_lifespan() -> None:
        """Enter the application lifespan until startup raises."""
        async with api_main.lifespan(api_main.app):
            pass

    with pytest.raises(RuntimeError, match="startup failed"):
        asyncio.run(exercise_lifespan())

    assert events == [
        "configured:local",
        "runtime-configured",
        "startup-failed",
        "observability-stopped",
    ]


def test_active_span_and_bound_domain_context_are_correlated() -> None:
    """Active W3C ids and sanitized domain ids are available together."""
    with capture_observability() as capture:
        with bind_correlation_context(
            request_id="request-1",
            run_id="run-1",
            step_id="step-1",
            tenant_id="tenant-1",
        ):
            with get_tracer().start_as_current_span("test") as span:
                assert current_trace_id() == f"{span.get_span_context().trace_id:032x}"
                assert current_span_id() == f"{span.get_span_context().span_id:016x}"
                assert current_correlation_context().run_id == "run-1"
        assert capture.span_exporter.get_finished_spans()


def test_nested_binding_restores_parent_and_hashes_unsafe_identifiers() -> None:
    """Nested bindings inherit omitted ids and restore their parent on exit."""
    unsafe = "tenant with private free text"
    with bind_correlation_context(run_id="run-parent", tenant_id=unsafe):
        parent = current_correlation_context()
        with bind_correlation_context(step_id="step-child"):
            child = current_correlation_context()
            assert child.run_id == "run-parent"
            assert child.step_id == "step-child"
            assert child.tenant_id == sanitize_identifier(unsafe)
        assert current_correlation_context() == parent
    assert current_correlation_context().run_id == ""


def test_correlation_carrier_propagates_w3c_and_domain_context() -> None:
    """A captured carrier restores both W3C trace state and domain identifiers."""
    with capture_observability():
        with bind_correlation_context(request_id="request-1", run_id="run-1"):
            with get_tracer().start_as_current_span("producer") as producer:
                carrier = capture_execution_context()
                producer_trace_id = producer.get_span_context().trace_id

        with bind_correlation_context(step_id="stale-step", tenant_id="stale-tenant"):
            with attach_execution_context(carrier):
                attached = current_correlation_context()
                assert attached.request_id == "request-1"
                assert attached.run_id == "run-1"
                assert attached.step_id == ""
                assert attached.tenant_id == ""
                with get_tracer().start_as_current_span("consumer") as consumer:
                    assert consumer.get_span_context().trace_id == producer_trace_id


def test_metric_sink_records_exact_instruments_and_bounded_dimensions() -> None:
    """Metric recordings expose the stable schema without raw correlation ids."""
    with capture_observability() as capture:
        with get_tracer().start_as_current_span("metric-exemplar"):
            capture.runtime.metric_sink.record_http_request(
                duration_seconds=0.25,
                method="GET",
                route="/v2/runs/{run_id}",
                status_code=200,
            )
        capture.runtime.metric_sink.record_run(
            duration_seconds=1.5,
            tenant_id="tenant-a",
            flow_id="flow-a",
            status="completed",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.01,
        )
        capture.runtime.metric_sink.record_step(
            tenant_id="tenant-a",
            agent_id="agent-a",
            status="completed",
            duration_seconds=0.5,
        )
        capture.runtime.metric_sink.record_decision(
            tenant_id="tenant-a",
            decision_type="route",
            outcome="selected",
        )
        capture.runtime.metric_sink.record_model_call(
            tenant_id="tenant-a",
            agent_id="agent-a",
            provider="provider-a",
            model="model-a",
            error_code="",
            duration_seconds=0.75,
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.01,
        )
        capture.runtime.metric_sink.record_evaluation(
            agent_id="agent-a",
            evaluator_id="evaluator-a",
            score=0.9,
            gate_passed=True,
        )
        capture.runtime.metric_sink.observe_queue(
            backend="inprocess",
            callback=lambda: QueueSnapshot(
                pending=2,
                running=1,
                workers=4,
                busy_workers=1,
            ),
        )
        metrics_data = capture.metric_reader.get_metrics_data()

    assert metrics_data is not None
    metrics = [
        metric
        for resource_metric in metrics_data.resource_metrics
        for scope_metric in resource_metric.scope_metrics
        for metric in scope_metric.metrics
    ]
    by_name = {metric.name: metric for metric in metrics}
    assert set(by_name) == {
        "http.server.request.duration",
        "autodev.run.duration",
        "autodev.run.step.duration",
        "autodev.run.step.count",
        "autodev.decision.count",
        "gen_ai.client.operation.duration",
        "autodev.model.tokens",
        "autodev.model.cost_usd",
        "autodev.agent.quality_ratio",
        "autodev.queue.jobs",
        "autodev.worker.utilization",
    }
    http_point = by_name["http.server.request.duration"].data.data_points[0]
    assert http_point.attributes == {
        "http.request.method": "GET",
        "http.route": "/v2/runs/{run_id}",
        "http.response.status_code": 200,
    }
    assert http_point.exemplars
    assert http_point.exemplars[0].trace_id
    for metric in metrics:
        for point in metric.data.data_points:
            attributes = point.attributes or {}
            assert "trace_id" not in attributes
            assert "run_id" not in attributes


def test_disabled_runtime_installs_no_export_processors() -> None:
    """The emergency rollback uses a no-op metric sink and no SDK providers."""
    runtime = configure_observability(
        Settings(otel_enabled=False), install_global=False
    )
    try:
        assert isinstance(runtime.metric_sink, NoopMetricSink)
        assert not get_tracer().start_span("disabled").is_recording()
    finally:
        runtime.shutdown()
