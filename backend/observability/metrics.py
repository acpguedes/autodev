"""Bounded three-signal metric recording interfaces and OTel instruments."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from opentelemetry.metrics import Meter, Observation

from backend.observability.context import sanitize_identifier


@dataclass(frozen=True)
class QueueSnapshot:
    """Bounded queue and worker state returned by queue backends.

    Attributes:
        pending: Number of jobs waiting to run.
        running: Number of jobs currently running.
        workers: Number of available workers.
        busy_workers: Number of workers currently executing jobs.
    """

    pending: int
    running: int
    workers: int
    busy_workers: int


class MetricSink(Protocol):
    """Stable application-facing interface for bounded operational metrics."""

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Record one completed HTTP server request.

        Args:
            method: Normalized HTTP method.
            route: Bounded route template, never a raw request path.
            status_code: HTTP response status code.
            duration_seconds: Request duration in seconds.
        """

    def record_run(
        self,
        *,
        tenant_id: str,
        flow_id: str,
        status: str,
        duration_seconds: float,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Record one completed AutoDev run.

        Args:
            tenant_id: Sanitized tenant identifier.
            flow_id: Sanitized flow identifier.
            status: Stable final run status.
            duration_seconds: Run duration in seconds.
            input_tokens: Total run input tokens.
            output_tokens: Total run output tokens.
            cost_usd: Estimated run cost in US dollars.
        """

    def record_step(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        """Record one completed run step.

        Args:
            tenant_id: Sanitized tenant identifier.
            agent_id: Sanitized agent identifier.
            status: Stable final step status.
            duration_seconds: Step duration in seconds.
        """

    def record_decision(
        self, *, tenant_id: str, decision_type: str, outcome: str
    ) -> None:
        """Record one bounded workflow decision.

        Args:
            tenant_id: Sanitized tenant identifier.
            decision_type: Stable decision category.
            outcome: Stable decision outcome.
        """

    def record_model_call(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        provider: str,
        model: str,
        error_code: str,
        duration_seconds: float,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Record one model-provider operation and its usage.

        Args:
            tenant_id: Sanitized tenant identifier.
            agent_id: Sanitized agent identifier.
            provider: Registered provider identifier.
            model: Provider model identifier.
            error_code: Stable error code, or an empty string on success.
            duration_seconds: Provider-operation duration in seconds.
            input_tokens: Normalized input token count.
            output_tokens: Normalized output token count.
            cost_usd: Estimated operation cost in US dollars.
        """

    def record_evaluation(
        self,
        *,
        agent_id: str,
        evaluator_id: str,
        score: float,
        gate_passed: bool,
    ) -> None:
        """Record one bounded agent evaluation ratio.

        Args:
            agent_id: Sanitized evaluated-agent identifier.
            evaluator_id: Sanitized evaluator identifier.
            score: Evaluation quality ratio.
            gate_passed: Whether the evaluation gate passed.
        """

    def observe_queue(
        self, *, backend: str, callback: Callable[[], QueueSnapshot]
    ) -> None:
        """Register a queue state callback for observable gauges.

        Args:
            backend: Stable queue-backend identifier.
            callback: Function returning the latest queue snapshot.
        """


class NoopMetricSink:
    """Metric sink used when OpenTelemetry is disabled."""

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Discard one HTTP request measurement."""

    def record_run(
        self,
        *,
        tenant_id: str,
        flow_id: str,
        status: str,
        duration_seconds: float,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Discard one run measurement."""

    def record_step(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        """Discard one step measurement."""

    def record_decision(
        self, *, tenant_id: str, decision_type: str, outcome: str
    ) -> None:
        """Discard one decision measurement."""

    def record_model_call(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        provider: str,
        model: str,
        error_code: str,
        duration_seconds: float,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Discard one model-operation measurement."""

    def record_evaluation(
        self,
        *,
        agent_id: str,
        evaluator_id: str,
        score: float,
        gate_passed: bool,
    ) -> None:
        """Discard one evaluation measurement."""

    def observe_queue(
        self, *, backend: str, callback: Callable[[], QueueSnapshot]
    ) -> None:
        """Discard a queue observation callback."""


class OtelMetricSink:
    """OpenTelemetry implementation of the stable application metric sink."""

    def __init__(self, meter: Meter) -> None:
        """Create the exact E11-S1 instruments on a meter.

        Args:
            meter: SDK meter owned by the observability runtime.
        """
        self._http_duration = meter.create_histogram(
            "http.server.request.duration", unit="s"
        )
        self._run_duration = meter.create_histogram("autodev.run.duration", unit="s")
        self._step_duration = meter.create_histogram(
            "autodev.run.step.duration", unit="s"
        )
        self._step_count = meter.create_counter("autodev.run.step.count", unit="{step}")
        self._decision_count = meter.create_counter(
            "autodev.decision.count", unit="{decision}"
        )
        self._model_duration = meter.create_histogram(
            "gen_ai.client.operation.duration", unit="s"
        )
        self._model_tokens = meter.create_counter(
            "autodev.model.tokens", unit="{token}"
        )
        self._model_cost = meter.create_counter("autodev.model.cost_usd", unit="USD")
        self._quality_ratio = meter.create_histogram(
            "autodev.agent.quality_ratio", unit="1"
        )
        self._queue_callbacks: dict[str, Callable[[], QueueSnapshot]] = {}
        meter.create_observable_gauge(
            "autodev.queue.jobs",
            callbacks=[self._observe_queue_jobs],
            unit="{job}",
        )
        meter.create_observable_gauge(
            "autodev.worker.utilization",
            callbacks=[self._observe_worker_utilization],
            unit="1",
        )

    @staticmethod
    def _safe(value: str) -> str:
        """Sanitize a metric dimension before recording it.

        Args:
            value: Candidate bounded dimension.

        Returns:
            A safe normalized or hashed identifier.
        """
        return sanitize_identifier(value)

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Record one completed HTTP server request."""
        self._http_duration.record(
            duration_seconds,
            {
                "http.request.method": method.upper(),
                "http.route": route,
                "http.response.status_code": status_code,
            },
        )

    def record_run(
        self,
        *,
        tenant_id: str,
        flow_id: str,
        status: str,
        duration_seconds: float,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Record one completed AutoDev run."""
        del input_tokens, output_tokens, cost_usd
        self._run_duration.record(
            duration_seconds,
            {
                "autodev.tenant": self._safe(tenant_id),
                "autodev.flow": self._safe(flow_id),
                "autodev.status": self._safe(status),
            },
        )

    def record_step(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        """Record one completed run step and increment its count."""
        attributes = {
            "autodev.tenant": self._safe(tenant_id),
            "autodev.agent": self._safe(agent_id),
            "autodev.status": self._safe(status),
        }
        self._step_duration.record(duration_seconds, attributes)
        self._step_count.add(1, attributes)

    def record_decision(
        self, *, tenant_id: str, decision_type: str, outcome: str
    ) -> None:
        """Record one bounded workflow decision."""
        self._decision_count.add(
            1,
            {
                "autodev.tenant": self._safe(tenant_id),
                "autodev.decision.type": self._safe(decision_type),
                "autodev.decision.outcome": self._safe(outcome),
            },
        )

    def record_model_call(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        provider: str,
        model: str,
        error_code: str,
        duration_seconds: float,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Record one model-provider operation and its usage."""
        attributes = {
            "autodev.tenant": self._safe(tenant_id),
            "autodev.agent": self._safe(agent_id),
            "gen_ai.provider.name": self._safe(provider),
            "gen_ai.request.model": self._safe(model),
        }
        duration_attributes = {
            **attributes,
            "error.type": self._safe(error_code),
        }
        self._model_duration.record(duration_seconds, duration_attributes)
        self._model_tokens.add(
            input_tokens, {**attributes, "gen_ai.token.type": "input"}
        )
        self._model_tokens.add(
            output_tokens, {**attributes, "gen_ai.token.type": "output"}
        )
        self._model_cost.add(cost_usd, attributes)

    def record_evaluation(
        self,
        *,
        agent_id: str,
        evaluator_id: str,
        score: float,
        gate_passed: bool,
    ) -> None:
        """Record one bounded agent evaluation ratio."""
        self._quality_ratio.record(
            score,
            {
                "autodev.agent": self._safe(agent_id),
                "autodev.evaluator": self._safe(evaluator_id),
                "autodev.gate.result": "passed" if gate_passed else "failed",
            },
        )

    def observe_queue(
        self, *, backend: str, callback: Callable[[], QueueSnapshot]
    ) -> None:
        """Register or replace a queue snapshot callback by backend name."""
        self._queue_callbacks[self._safe(backend)] = callback

    def _observe_queue_jobs(self, _: object) -> Iterable[Observation]:
        """Read queue callbacks for pending and running job observations."""
        for backend, callback in tuple(self._queue_callbacks.items()):
            snapshot = callback()
            yield Observation(
                snapshot.pending, {"backend": backend, "state": "pending"}
            )
            yield Observation(
                snapshot.running, {"backend": backend, "state": "running"}
            )

    def _observe_worker_utilization(self, _: object) -> Iterable[Observation]:
        """Read queue callbacks for worker-utilization observations."""
        for backend, callback in tuple(self._queue_callbacks.items()):
            snapshot = callback()
            value = (
                snapshot.busy_workers / snapshot.workers if snapshot.workers else 0.0
            )
            yield Observation(value, {"backend": backend})


_metric_sink: MetricSink = NoopMetricSink()


def get_metric_sink() -> MetricSink:
    """Return the process-owned application metric sink.

    Returns:
        The currently configured metric sink.
    """
    return _metric_sink


def set_metric_sink(sink: MetricSink) -> None:
    """Replace the process-owned metric sink.

    Args:
        sink: New sink owned by the active observability runtime.
    """
    global _metric_sink
    _metric_sink = sink


__all__ = [
    "MetricSink",
    "NoopMetricSink",
    "OtelMetricSink",
    "QueueSnapshot",
    "get_metric_sink",
    "set_metric_sink",
]
