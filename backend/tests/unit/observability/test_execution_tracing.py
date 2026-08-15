"""Execution-path tracing contracts for runs, steps, and decisions."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.agents.provider import StubLLMProvider
from backend.evals.contract import EvalCase
from backend.evals.service import EvaluationService
from backend.evals.spec import validate_eval_spec
from backend.observability import tracing
from backend.observability.tracing import get_tracer
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.reasoning import (
    ReasoningInput,
    ReasoningService,
    ReasoningStrategyRegistry,
    budget_from_policy,
    default_reasoning_policy,
)
from backend.reasoning.strategies import register_builtin_strategies
from backend.routing.contract import (
    ROUTE_SCHEMA_VERSION,
    RouteInput,
    RouteRequest,
    TraceEvent,
)
from backend.routing.policy import default_routing_policy
from backend.routing.service import RoutingService
from backend.tests.observability_helpers import capture_observability
from backend.validation.models import ValidationJob
from backend.validation.sandbox import SandboxRunner


def test_trace_run_interface_is_available() -> None:
    """The frozen execution tracing interfaces are exported for callers."""
    assert callable(getattr(tracing, "trace_run", None))
    assert callable(getattr(tracing, "trace_run_step", None))
    assert callable(getattr(tracing, "trace_dependency", None))
    assert callable(getattr(tracing, "record_decision", None))


def test_reasoning_output_keeps_a_domain_uuid_distinct_from_w3c_trace() -> None:
    """Operational tracing must not replace the replay/audit UUID anchor."""
    registry = ReasoningStrategyRegistry()
    register_builtin_strategies(registry)
    service = ReasoningService(
        registry,
        provider=StubLLMProvider(text="FINAL: ok"),
    )
    policy = default_reasoning_policy(default_strategy="autodev/reasoning-native-tools")
    run_input = ReasoningInput(
        task="test",
        messages=(),
        tools=(),
        policy=policy,
        budget=budget_from_policy(policy),
    )

    with capture_observability() as capture:
        with get_tracer().start_as_current_span("operational") as span:
            w3c_trace_id = f"{span.get_span_context().trace_id:032x}"
            result = asyncio.run(service.run(run_input))

    assert result.output.trace_id
    assert result.output.trace_id != w3c_trace_id
    assert len(result.output.trace_id) == 36
    decision_spans = [
        span
        for span in capture.span_exporter.get_finished_spans()
        if span.name.startswith("autodev.decision.reasoning.")
    ]
    assert decision_spans
    assert "test" not in repr(decision_spans)


def test_routing_records_a_safe_decision_and_preserves_callback() -> None:
    """Routing telemetry excludes task/rationale/path and keeps replay events."""
    secret_task = "sk-sensitive-routing"
    events: list[TraceEvent] = []
    request = RouteRequest(
        schema_version=ROUTE_SCHEMA_VERSION,
        session_id="session-1",
        run_id="run-1",
        input=RouteInput(text=secret_task),
    )
    with capture_observability() as capture:
        decision = RoutingService(
            default_routing_policy(), on_event=events.append
        ).route(request)

    spans = [
        span
        for span in capture.span_exporter.get_finished_spans()
        if span.name == "autodev.decision.router.decision.recorded"
    ]
    assert len(spans) == 1
    attributes = spans[0].attributes
    assert attributes is not None
    assert attributes["autodev.decision.task_type"] == decision.task_type
    assert attributes["autodev.run_id"] == "run-1"
    assert len(events) == 1
    assert events[0].payload["path"] == list(decision.path)
    assert secret_task not in repr(spans)
    assert decision.rationale not in repr(spans)


def test_sandbox_dependency_records_only_bounded_operational_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sandbox telemetry excludes command and process output content."""
    secret_command = "sk-sensitive-command"
    monkeypatch.delenv("AUTODEV_ENABLE_SANDBOX", raising=False)
    with capture_observability() as capture:
        result = SandboxRunner().run(
            ValidationJob("job-1", ["python", "-c", secret_command])
        )

    span = next(
        span
        for span in capture.span_exporter.get_finished_spans()
        if span.name == "autodev.dependency.sandbox"
    )
    assert result.skipped is True
    attributes = span.attributes
    assert attributes is not None
    assert attributes["autodev.status"] == "skipped"
    assert attributes["autodev.sandbox.backend"] == "disabled"
    assert secret_command not in repr(attributes)
    assert secret_command not in repr(span.events)


def test_evaluation_metrics_are_recorded_after_persistence(tmp_path: Path) -> None:
    """Each persisted quality metric emits one bounded evaluation point."""
    parsed = validate_eval_spec(
        {
            "schemaVersion": "1.0",
            "id": "autodev/eval-observability",
            "version": "1.0.0",
            "target": {"kind": "agent", "agent_id": "autodev/agent-coder"},
            "mode": "offline",
            "dataset": {"ref": "autodev/test@1", "split": "test", "size": 1},
            "evaluators": [
                {
                    "kind": "deterministic",
                    "id": "tests_pass",
                    "check": "sandbox.tests.exit_code == 0",
                }
            ],
            "metrics": {"quality": {"primary": "tests_pass"}},
        }
    )
    assert parsed.spec is not None
    store = SQLiteStore(f"sqlite:///{tmp_path / 'evals.db'}")
    with capture_observability() as capture:
        EvaluationService(store).run_offline(
            parsed.spec,
            [EvalCase("case-1", {"sandbox": {"tests": {"exit_code": 0}}})],
        )
        capture.runtime.force_flush()

    metrics_data = capture.metric_reader.get_metrics_data()
    assert metrics_data is not None
    quality_points = [
        point
        for resource in metrics_data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "autodev.agent.quality_ratio"
        for point in metric.data.data_points
    ]
    assert len(quality_points) == 1
    point_attributes = quality_points[0].attributes
    assert point_attributes is not None
    assert point_attributes["autodev.evaluator"] == "tests_pass"
    assert point_attributes["autodev.gate.result"] == "passed"


def test_orchestrator_run_span_closes_after_durable_completion(
    tmp_path: Path,
) -> None:
    """The orchestrator emits one terminal run span around durable execution."""
    service = OrchestratorService(
        store=DurableStore(f"sqlite:///{tmp_path / 'orchestrator.db'}")
    )
    session = service.create_plan("Ship observability")
    with capture_observability() as capture:
        result = service.handle_message(session.session_id, "Start execution")

    run_spans = [
        span
        for span in capture.span_exporter.get_finished_spans()
        if span.name == "autodev.run"
    ]
    assert len(run_spans) == 1
    attributes = run_spans[0].attributes
    assert attributes is not None
    assert attributes["autodev.run_id"] == result.run_id
    assert attributes["autodev.status"] == "completed"
