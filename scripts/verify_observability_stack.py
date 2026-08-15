"""Emit and verify a deterministic three-signal observability smoke sample."""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config.settings import Settings  # noqa: E402
from backend.observability.context import bind_correlation_context  # noqa: E402
from backend.observability.runtime import configure_observability  # noqa: E402

SMOKE_SERVICE_NAME = "autodev-observability-smoke"
COLLECTOR_ENDPOINT = "http://localhost:4318"
POLL_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 1.0

JsonObject = dict[str, Any]
RequestJson = Callable[[str, float], JsonObject]


class VerificationError(RuntimeError):
    """Raised when the local observability stack does not pass its smoke check."""


@dataclass(frozen=True)
class BackendCheck:
    """Describe one queryable backend readiness contract.

    Attributes:
        name: Human-readable backend name used in output.
        url: Exact health or signal query URL.
        ready: Predicate recognizing a successful searchable response.
    """

    name: str
    url: str
    ready: Callable[[Mapping[str, Any]], bool]


def _request_json(url: str, timeout_seconds: float) -> JsonObject:
    """Fetch and decode one JSON response using only the Python standard library.

    Args:
        url: HTTP endpoint to query.
        timeout_seconds: Per-request socket timeout.

    Returns:
        Decoded JSON object.

    Raises:
        OSError: If the endpoint cannot be reached.
        ValueError: If the response is not a JSON object.
    """
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("response is not a JSON object")
    return payload


def _grafana_ready(payload: Mapping[str, Any]) -> bool:
    """Return whether Grafana reports a healthy database connection."""
    return payload.get("database") == "ok"


def _prometheus_ready(payload: Mapping[str, Any]) -> bool:
    """Return whether Prometheus found the emitted step histogram."""
    data = payload.get("data")
    return (
        payload.get("status") == "success"
        and isinstance(data, Mapping)
        and bool(data.get("result"))
    )


def _tempo_ready(payload: Mapping[str, Any]) -> bool:
    """Return whether Tempo found the emitted smoke service trace."""
    return bool(payload.get("traces"))


def _loki_ready(payload: Mapping[str, Any]) -> bool:
    """Return whether Loki found the emitted smoke service log."""
    data = payload.get("data")
    return (
        payload.get("status") == "success"
        and isinstance(data, Mapping)
        and bool(data.get("result"))
    )


def build_backend_checks() -> tuple[BackendCheck, ...]:
    """Build the four deterministic health and signal queries.

    Returns:
        Grafana, Prometheus, Tempo, and Loki checks in display order.
    """
    prometheus_query = urlencode({"query": "autodev_run_step_duration_count"})
    tempo_query = urlencode(
        {"q": f'{{resource.service.name="{SMOKE_SERVICE_NAME}"}}'}
    )
    loki_query = urlencode(
        {"query": f'{{service_name="{SMOKE_SERVICE_NAME}"}}', "limit": "1"}
    )
    return (
        BackendCheck(
            name="Grafana",
            url="http://localhost:3001/api/health",
            ready=_grafana_ready,
        ),
        BackendCheck(
            name="Prometheus",
            url=f"http://localhost:9090/api/v1/query?{prometheus_query}",
            ready=_prometheus_ready,
        ),
        BackendCheck(
            name="Tempo",
            url=f"http://localhost:3200/api/search?{tempo_query}",
            ready=_tempo_ready,
        ),
        BackendCheck(
            name="Loki",
            url=f"http://localhost:3100/loki/api/v1/query_range?{loki_query}",
            ready=_loki_ready,
        ),
    )


def emit_smoke_signals(
    *,
    collector_endpoint: str = COLLECTOR_ENDPOINT,
    service_name: str = SMOKE_SERVICE_NAME,
) -> None:
    """Export one correlated run, step, model call, metric set, and JSON log.

    Args:
        collector_endpoint: Host-accessible Collector OTLP/HTTP base URL.
        service_name: Deterministic resource service name used by backend queries.

    Raises:
        VerificationError: If all providers cannot be force-flushed.
    """
    settings = Settings(
        otel_enabled=True,
        otel_service_name=service_name,
        otel_exporter_otlp_endpoint=collector_endpoint,
        otel_traces_sampler="always_on",
        otel_metric_export_interval_ms=1_000,
    )
    runtime = configure_observability(
        settings,
        service_name=service_name,
        install_global=False,
    )
    tracer = runtime.tracer_provider.get_tracer("autodev.observability.smoke")
    logger = logging.getLogger("autodev.observability.smoke")
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    try:
        with bind_correlation_context(
            request_id="smoke-request",
            run_id="smoke-run",
            tenant_id="smoke-tenant",
        ):
            with tracer.start_as_current_span(
                "autodev.run",
                attributes={
                    "autodev.run_id": "smoke-run",
                    "autodev.status": "completed",
                },
            ):
                with bind_correlation_context(step_id="smoke-step"):
                    with tracer.start_as_current_span(
                        "autodev.run.step.smoke",
                        attributes={
                            "autodev.agent_id": "smoke-agent",
                            "autodev.status": "completed",
                        },
                    ):
                        runtime.metric_sink.record_step(
                            tenant_id="smoke-tenant",
                            agent_id="smoke-agent",
                            status="completed",
                            duration_seconds=0.01,
                        )
                    with tracer.start_as_current_span(
                        "autodev.model.call",
                        attributes={
                            "gen_ai.provider.name": "smoke-provider",
                            "gen_ai.request.model": "smoke-model",
                            "autodev.status": "completed",
                        },
                    ):
                        runtime.metric_sink.record_model_call(
                            tenant_id="smoke-tenant",
                            agent_id="smoke-agent",
                            provider="smoke-provider",
                            model="smoke-model",
                            error_code="",
                            duration_seconds=0.01,
                            input_tokens=1,
                            output_tokens=1,
                            cost_usd=0.001,
                        )
                        logger.info(
                            "observability smoke completed",
                            extra={
                                "event": "observability.smoke.completed",
                                "status": "completed",
                            },
                        )
                runtime.metric_sink.record_run(
                    tenant_id="smoke-tenant",
                    flow_id="smoke-flow",
                    status="completed",
                    duration_seconds=0.03,
                    input_tokens=1,
                    output_tokens=1,
                    cost_usd=0.001,
                )
        if not runtime.force_flush(timeout_millis=10_000):
            raise VerificationError("Collector export force-flush did not complete")
    finally:
        root_logger.setLevel(previous_level)
        runtime.shutdown()


def wait_for_backends(
    checks: Sequence[BackendCheck],
    *,
    timeout_seconds: float = POLL_TIMEOUT_SECONDS,
    request_json: RequestJson = _request_json,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Poll all backends against one shared bounded deadline.

    Args:
        checks: Backend health and query contracts to satisfy.
        timeout_seconds: Total polling budget shared by all checks.
        request_json: Injectable JSON request function.
        monotonic: Injectable monotonic clock.
        sleep: Injectable wait function.

    Raises:
        VerificationError: If any backend remains unavailable at the deadline.
    """
    deadline = monotonic() + max(0.0, timeout_seconds)
    pending = {check.name: check for check in checks}
    failures = {check.name: "response not ready" for check in checks}
    while pending:
        for name, check in tuple(pending.items()):
            remaining = max(0.1, deadline - monotonic())
            try:
                payload = request_json(check.url, min(2.0, remaining))
                if check.ready(payload):
                    print(f"[ok] {name}: {check.url}")
                    del pending[name]
                else:
                    failures[name] = "response did not contain the smoke result"
            except Exception as exc:  # Backend response errors are retryable here.
                failures[name] = f"{type(exc).__name__}: {exc}"
        if not pending:
            return
        now = monotonic()
        if now >= deadline:
            details = "\n".join(
                f"- {name}: {check.url} ({failures[name]})"
                for name, check in pending.items()
            )
            raise VerificationError(
                f"backends unavailable after {timeout_seconds:.1f}s:\n{details}"
            )
        sleep(min(POLL_INTERVAL_SECONDS, deadline - now))


def main() -> int:
    """Run the live observability smoke check.

    Returns:
        Zero when every backend contains the emitted signal; one otherwise.
    """
    try:
        print(f"Emitting smoke signals through {COLLECTOR_ENDPOINT}")
        emit_smoke_signals()
        wait_for_backends(build_backend_checks())
    except VerificationError as exc:
        print(f"observability verification failed: {exc}", file=sys.stderr)
        return 1
    print("Observability stack verified: metrics, traces, and logs are searchable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
