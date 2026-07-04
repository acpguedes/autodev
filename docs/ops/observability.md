# Observability

E0 promotes observability from best-effort request counters to a configured
OpenTelemetry baseline.

## Signals

- HTTP requests emit spans named `http.server <METHOD> <PATH>`.
- Agent workflow steps emit spans named `autodev.run.step.<step_id>`.
- Step spans include only non-PII correlation attributes:
  - `autodev.run_id`
  - `autodev.step_id`
  - `autodev.agent`
  - `autodev.status`
- `/metrics` exposes request counts, cumulative latency, and HTTP 5xx error
  counters in Prometheus text format.

## Configuration

```env
OTEL_SERVICE_NAME=autodev-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0
```

When `OTEL_EXPORTER_OTLP_ENDPOINT` is empty, spans still use the configured
OpenTelemetry provider but are not exported.

## Base Dashboard Panels

A staging dashboard should include:

- request rate by path;
- p95 request duration by path;
- 5xx error count and error rate;
- run-step span count by agent;
- slowest run-step spans grouped by `autodev.agent`.

## Base Alert

The first staging alert should fire when 5xx error rate exceeds 5% for five
minutes on any API path.
