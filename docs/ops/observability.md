# Observability

E11-S1 instruments the platform with a typed, three-signal OpenTelemetry
runtime and a self-hosted OSS backend stack. Every run/step/decision/model
call is traceable end to end, correlated across traces, structured logs, and
metrics by `run_id`/`trace_id`.

## Architecture and signal flow

```
backend (FastAPI, Flow engine, Agent Runtime, jobs)
  --OTLP/HTTP--> otel-collector:4318
                   |-- traces  --> tempo:4317   (otlphttp/tempo)
                   |-- metrics --> Prometheus scrape of otel-collector:9464
                   \-- logs    --> loki:3100    (otlphttp/loki)

prometheus:9090 --(datasource)--> grafana:3001
tempo:3200      --(datasource)--> grafana:3001
loki:3100       --(datasource)--> grafana:3001

prometheus:9090 --(alerts)--> alertmanager:9093
```

`infrastructure/observability/otel-collector.yaml` receives OTLP/gRPC and
OTLP/HTTP on `4317`/`4318`, batches, and fans out each signal to exactly one
exporter (`otlphttp/tempo`, `prometheus`, `otlphttp/loki`). Backend processes
never talk to Tempo, Loki, or Prometheus directly — the Collector is the only
export target.

## Bringing the stack up

```bash
make observability-up      # start backend + tempo/loki/otel-collector/prometheus/grafana
make observability-verify  # scripts/verify_observability_stack.py: emit a smoke
                            # run/step/model-call/log, poll all four backends
make observability-down    # stop the stack; named volumes are preserved
```

`observability-down` never passes `-v` — operator data (traces, metrics,
logs, dashboards) survives a stack restart. To discard it, remove the named
volumes explicitly.

## Ports and backend responsibilities

| Service | Port (host) | Responsibility |
| --- | --- | --- |
| `otel-collector` | `4318` (OTLP/HTTP), `9464` (Prometheus exporter) | Receive, batch, and route all three signals. |
| `prometheus` | `9090` | Scrape the Collector's Prometheus exporter; store metrics and evaluate recording rules. |
| `tempo` | `3200` | Store and query traces. |
| `loki` | `3100` | Store and query structured logs. |
| `grafana` | `3001` | Dashboards, provisioned datasources, exemplar/trace-to-logs navigation. |
| `alertmanager` | `9093` | Receive, group, and route firing alerts from Prometheus (E11-S4). |

## Alert routing (E11-S4)

Prometheus evaluates alert rules from the same shared
`infrastructure/observability/prometheus-rules.yml` used for recording rules
(`rule_files`), and delivers firing alerts to
`infrastructure/observability/alertmanager.yml` per its `alerting.alertmanagers`
static config. The E11-S4 backup alerts
(`AutoDevBackupNeverSucceeded`/`AutoDevBackupStale`/`AutoDevBackupFailing`)
are the current alert set; each carries `severity`, `service`, `summary`,
`description`, and an HTTPS `runbook_url` pointing at
`docs/v2_platform/runbooks/e11_incident_response.md`.

Alertmanager ships with one `operator-ui` receiver and a default route
(`infrastructure/observability/alertmanager.yml`) — alerts are visible and
groupable in Alertmanager's own UI (`http://localhost:9093`) out of the box,
with no external notification service required. To route alerts to
email/Slack/PagerDuty/webhook, replace or extend the `receivers:` list with
your integration (see the [Alertmanager configuration
docs](https://prometheus.io/docs/alerting/latest/configuration/)) and update
`route.receiver` accordingly. **Never hardcode external notification
credentials into `alertmanager.yml`** — mount them via a separate,
untracked config file or environment-templated secret, matching the
credential-handling posture in `docs/security.md`.

## Span and metric naming

Spans (`backend/observability/tracing.py`):

- `autodev.run` — one run, closed with `autodev.status`, `autodev.error_code`,
  `autodev.tokens.input/output`, `autodev.cost_usd`.
- `autodev.run.step.<step_id>` — one run step, attributes `autodev.run_id`,
  `autodev.step_id`, `autodev.agent`, `autodev.tenant_id`, `autodev.status`,
  `autodev.error_code`.
- `autodev.dependency.<tool|skill|sandbox>` — one bounded tool/skill/sandbox
  call.
- `autodev.decision.<name>` — one content-free routing/gate decision.
- `autodev.model.call` — one provider attempt, credential- and prompt-free
  (`autodev.model.provider`, `autodev.model.name`, `autodev.model.latency_ms`,
  token/cost fields, `autodev.model.error_code`).
- `http.server <METHOD> <ROUTE>` — one inbound HTTP request.

Metrics (`backend/observability/metrics.py`, all `autodev.*` unless noted):

| Metric | Kind | Notes |
| --- | --- | --- |
| `http.server.request.duration` | histogram | `http.request.method`, `http.route`, `http.response.status_code`. |
| `autodev.run.duration` | histogram | `autodev.tenant`, `autodev.flow`, `autodev.status`. |
| `autodev.run.step.duration` | histogram | `autodev.tenant`, `autodev.agent`, `autodev.status`. |
| `autodev.run.step.count` | counter | Same dimensions as step duration. |
| `autodev.decision.count` | counter | `autodev.decision.type`, `autodev.decision.outcome`. |
| `gen_ai.client.operation.duration` | histogram | `gen_ai.request.model` and other `gen_ai.*` semantic-convention attributes. |
| `autodev.model.tokens` | counter | `autodev.token_type` (input/output). |
| `autodev.model.cost_usd` | counter | Per-tenant model spend. |
| `autodev.agent.quality_ratio` | histogram | Agent evaluation score. |
| `autodev.queue.jobs` | observable gauge | `state` (pending/running). |
| `autodev.worker.utilization` | observable gauge | Fraction of workers busy. |
| `autodev.postgres.pool.wait_duration` | histogram | `outcome` (granted/timeout) — no tenant dimension (E60-S4). |
| `autodev.postgres.transient_error.count` | counter | `error_type` (deadlock/serialization_failure) — no tenant dimension (E60-S4). |
| `autodev.postgres.pool.stat` | observable gauge | `stat` — the pool implementation's own fixed counter names (`pool_min`, `pool_max`, `pool_available`, `requests_waiting`, ...) (E60-S4). |

Recording rules in `infrastructure/observability/prometheus-rules.yml` derive
`autodev:http_error_ratio:rate5m` and `autodev:http_latency_p95_seconds:rate5m`
so dashboards and (E11-S4) alerts query a stable rule name instead of
recomputing the same `rate()`/`histogram_quantile()` expression everywhere.

## Metric-label cardinality policy

Every label is a bounded, stable identifier: `sanitize_identifier()`
(`backend/observability/context.py`) accepts `[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}`
and replaces anything else — including raw user input, file paths, and
unbounded free text — with a stable `sha256:<24-hex>` digest. No metric label
ever carries a run id, trace id, span id, step id, raw filesystem path,
prompt, or payload; those stay on spans and logs only, which Prometheus never
ingests. This bounds label cardinality to the number of tenants, flows,
agents, statuses, and error codes in play, not the number of runs.

The three `autodev.postgres.*` instruments (E60-S4) additionally carry no
tenant label at all: pool checkouts and deadlock/serialization classification
are process-wide, not tenant-scoped, so per-tenant volumes never belong on
them (per-tenant PostgreSQL activity, if ever needed, would have to come from
an aggregate, not a label).

## Trace exemplar navigation

`infrastructure/observability/grafana/provisioning/datasources/datasources.yaml`
provisions three datasources with stable UIDs — `prometheus`, `tempo`, `loki`
— so dashboard JSON and links never depend on Grafana-generated UIDs:

- Prometheus exemplars carry `trace_id` and link directly to the matching
  Tempo trace.
- Tempo is configured with a trace-to-logs link into Loki, and with a
  service-map data source pointed back at Prometheus.
- Loki has a derived field matching `"trace_id":"([0-9a-f]{32})"` in the raw
  JSON log line, linking to the matching Tempo trace.

This lets an operator start from a latency spike on a Prometheus panel, jump
to the exemplar trace in Tempo, and from there jump to the correlated logs in
Loki — one 32-character W3C trace id ties all three signals together.

## JSON log schema and redaction policy

Every log line is one JSON object on stdout
(`backend/observability/log_correlation.py`):

```json
{"timestamp":"2026-08-15T09:07:21.239211+00:00","severity":"INFO","logger":"autodev.observability.smoke","message":"observability smoke completed","request_id":"smoke-request","run_id":"smoke-run","step_id":"smoke-step","tenant_id":"smoke-tenant","trace_id":"27f0d2b63727f6c279090ac93f0571a1","span_id":"b96c617d4c40ec66","event":"observability.smoke.completed","status":"completed"}
```

`timestamp`, `severity`, `logger`, and `message` are always present.
`request_id`/`run_id`/`step_id`/`tenant_id` come from the active
`CorrelationContext`; `trace_id`/`span_id` come from the active OTel span
when one is recording. `event`, `status`, `duration_s`, `error_code`,
`method`, and `route` are included only when the log call passes them.

Every record and every `extra` mapping passes through
`TelemetryRedactionFilter` before formatting:

- Keys containing `authorization`, `cookie`, `credential`, `password`,
  `secret`, `token`, `api_key`, `access_key`, or `private_key` are replaced
  with `[REDACTED]` regardless of value.
- Bearer tokens, `key=value`/`key: value` credential patterns, and common
  vendor API key shapes (`sk-...`, `ghp_...`, `xoxb-...`, `AIza...`) are
  redacted from free-text string values.
- Email addresses are redacted from free-text string values.

This applies identically whether OTel export is enabled or not — the
redaction filter sits on the stdout JSON handler, which is always installed.

## Sampling modes and parent behavior

`OTEL_TRACES_SAMPLER` accepts `always_on`, `always_off`, `traceidratio`,
`parentbased_always_on`, `parentbased_always_off`, and
`parentbased_traceidratio` (default, `OTEL_TRACES_SAMPLER_ARG=1.0`, i.e.
sample everything). The `parentbased_*` variants respect an already-sampled
parent context from an upstream caller instead of re-rolling the sampling
decision, so a trace stays fully connected end to end even when a service
boundary sits between two instrumented components.

## Retention ownership and volume behavior

Retention is operator-configured, not code-defaulted, so it survives without
a redeploy:

- Traces: Tempo's compactor reads `${AUTODEV_OBSERVABILITY_TRACE_RETENTION}`
  (`infrastructure/observability/tempo.yaml`, default `168h`).
- Logs: Loki's `limits_config.retention_period` reads
  `${AUTODEV_OBSERVABILITY_LOG_RETENTION}` with compactor retention enabled
  (`infrastructure/observability/loki.yaml`, default `168h`).
- Metrics: Prometheus is started with
  `--storage.tsdb.retention.time=${AUTODEV_OBSERVABILITY_METRIC_RETENTION:-15d}`
  (`infrastructure/docker-compose.yml`).

Both Tempo and Loki start with `-config.expand-env=true` so these `${...}`
references are actually resolved rather than treated as literal text. Each
backend uses a named Docker volume; `make observability-down` never adds
`-v`, so operator data is not deleted by a routine restart.

## Dashboard panels and queries

`infrastructure/observability/grafana/dashboards/autodev-overview.json`
(auto-provisioned by
`infrastructure/observability/grafana/provisioning/dashboards/dashboards.yaml`)
ships thirteen panels:

| Panel | Query |
| --- | --- |
| HTTP Request Rate | `sum(rate(http_server_request_duration_count[5m])) by (http_route)` |
| HTTP Error Ratio | `autodev:http_error_ratio:rate5m` |
| HTTP Latency p95 | `autodev:http_latency_p95_seconds:rate5m` |
| Run and Step Latency p95 | `histogram_quantile(0.95, sum by (le, autodev_agent_id) (rate(autodev_run_step_duration_bucket[5m])))` |
| Model Latency p95 | `histogram_quantile(0.95, sum by (le, gen_ai_request_model) (rate(gen_ai_client_operation_duration_bucket[5m])))` |
| Cost by Tenant | `sum(increase(autodev_model_cost_usd_total[$__range])) by (autodev_tenant_id)` |
| Tokens by Tenant | `sum(increase(autodev_model_tokens_total[$__range])) by (autodev_tenant_id, autodev_token_type)` |
| Agent Quality | `sum(autodev_agent_quality_ratio_sum) by (autodev_agent_id) / clamp_min(sum(autodev_agent_quality_ratio_count) by (autodev_agent_id), 1)` |
| Queue Depth | `autodev_queue_jobs{state="pending"}` |
| Worker Utilization | `autodev_worker_utilization` |
| Postgres Pool Available Connections | `autodev_postgres_pool_stat{stat="pool_available"}` |
| Postgres Pool Wait p95 | `histogram_quantile(0.95, sum by (le, outcome) (rate(autodev_postgres_pool_wait_duration_bucket[5m])))` |
| Postgres Deadlock Rate | `sum(rate(autodev_postgres_transient_error_count_total{error_type="PostgresDeadlockError"}[5m]))` |

## Expected failure modes

- **Collector unreachable**: `configure_observability` still installs
  in-process tracer/meter/logger providers; spans, metrics, and JSON logs
  keep working locally, they simply are not exported. `force_flush()` in
  `scripts/verify_observability_stack.py` fails fast rather than hanging.
- **Prometheus finds no series for the smoke metric**: check
  `honor_labels: true` is present on the `otel-collector` scrape job in
  `infrastructure/observability/prometheus.yaml` — without it Prometheus
  overwrites the exporter's own `job` label with the scrape job name
  (`otel-collector`) and moves the original to `exported_job`, so a
  job-scoped query silently returns nothing even though the metric exists.
- **Grafana panels show "No data" for exemplars**: confirm the datasource
  UIDs in the dashboard JSON match the provisioned `prometheus`/`tempo`/`loki`
  UIDs — a UID mismatch breaks exemplar and derived-field links without
  breaking the panel's own base query.
- **`make observability-verify` times out**: it polls all four backends
  against one shared 30-second deadline and prints the first failing URL and
  reason per backend; start with that URL against `curl` before assuming the
  stack is unhealthy.

## Validating alert and rule configuration

Validate rule and Alertmanager syntax without needing a live incident:

```bash
docker compose -f infrastructure/docker-compose.yml --profile observability config -q
docker compose -f infrastructure/docker-compose.yml --profile observability run --rm \
  --entrypoint /bin/promtool prometheus check rules /etc/prometheus/prometheus-rules.yml
docker compose -f infrastructure/docker-compose.yml --profile observability run --rm \
  --entrypoint /bin/amtool alertmanager check-config /etc/alertmanager/alertmanager.yml
```

With the stack up (`make observability-up`), confirm Prometheus actually
reached Alertmanager and loaded the rule group:

```bash
curl -s http://localhost:9090/api/v1/alertmanagers
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[] | select(.name=="autodev-e11-s4-backup")'
```

## Emergency rollback

Set `OTEL_ENABLED=false` and restart the backend. Tracing, metrics, and
logging fall back to no-op providers with zero Collector dependency — the
application starts and serves requests identically, it just stops emitting
telemetry. No code change or redeploy of the observability stack is required.

## Out of scope for E11-S1 (delivered by E11-S4)

Alert delivery (Alertmanager, the backup alert rules, and the incident
response runbook) and backup/security operational runbooks were out of scope
for E11-S1 and are now delivered by E11-S4 — see "Alert routing" above and
`docs/v2_platform/runbooks/e11_incident_response.md`. Quota/budget alerts
remain E11-S3 work.
