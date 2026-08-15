# ADR-017: Three-Signal Observability Runtime and OSS Backends

- **Status:** Accepted
- **Date:** 2026-08-15
- **Authors:** AutoDev maintainers
- **Related epic:** E11-S1
- **Supersedes/Relates to:** None

## Context

AutoDev needs correlated traces, metrics, and logs that remain useful in a
self-hosted deployment without leaking credentials, user content, or unbounded
identifiers. The application also needs one explicit lifecycle and a local mode
that does not require an observability backend.

## Decision

Applications send all three signals over OTLP/HTTP to an OpenTelemetry
Collector gateway. The default self-hosted OSS profile uses Tempo for traces,
Prometheus for metrics, Loki for logs, and Grafana for visualization. Direct
application exporters to those individual backends are not supported by the
default profile.

Metrics link to active traces through trace-based exemplars. Trace IDs, run IDs,
and other high-cardinality identifiers are not metric labels. JSON logs and OTel
logs pass through the same mutating redaction filter before emission.

The default retention periods are `168h` for traces, `15d` for metrics, and
`168h` for logs. Sampling defaults to `parentbased_traceidratio` with ratio
`1.0`. Empty exporter endpoints mean local no-export operation. Setting
`OTEL_ENABLED=false` is the emergency rollback and disables all OTel export
processors. Alert delivery and comprehensive operational runbooks remain in
E11-S4.

## Alternatives considered

1. **Require a paid observability SaaS** — rejected because it would undermine
   self-hosting and make an external paid service a platform dependency.
2. **Export directly from the application to each backend** — rejected because
   backend-specific concerns would enter application configuration and lifecycle
   code instead of remaining at the Collector gateway.
3. **Attach trace or run IDs as metric labels** — rejected because unbounded
   label cardinality threatens metric-store reliability; exemplars provide the
   required trace link without that cost.

## Consequences

- **Positive:** Operators get correlated, vendor-neutral signals and an OSS-first
  default deployment while local development stays dependency-free.
- **Negative / trade-offs:** Production observability depends on correct
  Collector routing, and trace-based exemplars require sampled trace context.
- **Contract impact:** E11-S1 adds typed runtime and configuration interfaces;
  existing tracing helpers remain compatibility wrappers.

## Rollback plan

Set `OTEL_ENABLED=false` to remove export processors immediately while retaining
application behavior and local structured logging. Emptying signal endpoints
also restores local no-export operation without changing application code.

## References

- `docs/architecture/v2_platform_reference.md` §18.7 and §19.3.
- Story E11-S1.
