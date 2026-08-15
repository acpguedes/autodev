# E11-S1 OpenTelemetry Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver E11-S1 so traces, metrics, logs, domain events, and decision traces are correlated end to end; operators can run an entirely OSS observability stack with latency/error/cost dashboards; sampling and signal retention are explicit and configurable; representative instrumentation overhead remains below the E0 `<5%` target.

**Architecture:** The application owns one typed `ObservabilityRuntime` containing OpenTelemetry trace, metric, and log providers. HTTP middleware extracts W3C Trace Context, execution context managers bind `request_id`/`run_id`/`step_id`/`tenant_id`, metrics use trace-based exemplars instead of high-cardinality trace/run labels, and structured JSON logs derive trace/span IDs from the active span. Signals are exported over OTLP/HTTP to an OpenTelemetry Collector, then routed to Tempo, Prometheus, and Loki; Grafana is provisioned with all three data sources and one operational dashboard.

**Tech Stack:** Python 3.10+, FastAPI/ASGI, OpenTelemetry Python 1.43-compatible APIs, OTLP/HTTP, OpenTelemetry Collector Contrib, Prometheus, Tempo, Loki, Grafana, Docker Compose, pytest.

**Spec:** `docs/v2_platform/phases/e11_observability_security_multitenant.md` E11-S1; `docs/architecture/v2_platform_reference.md` §14.1, §16.5, §16.6, §18.3, and §18.7.5; E0 tracing-overhead target in §18.6.

## Global Constraints

- Implement only E11-S1-T1 through E11-S1-T3. RBAC, quotas, tenant enforcement, sandbox hardening, backup alerts, Alertmanager receiver delivery, and the comprehensive incident/runbook catalog remain E11-S2 through E11-S4.
- Work on `story/e11-s1-observability`, cut from `epic/e11-observability-security-multitenant`. Merge the completed story into the epic branch with `--no-ff`; do not merge the incomplete E11 epic into `main`.
- Activate the project virtualenv for every Python command: `source .venv/bin/activate && <command>`.
- Preserve the existing `GET /metrics` endpoint and `MetricsRegistry` as a compatibility surface. New dashboards consume OTel metrics from the Collector's Prometheus exporter.
- Preserve all public reasoning/routing/evaluation callback payloads and ordering.
- Preserve `ReasoningOutput.trace_id` as the durable replay/audit anchor. It is not the W3C trace ID. Operational W3C IDs come from `current_trace_id()`.
- Preserve `EventEnvelope` schema version and fields. Only change the defaulting behavior so an omitted `trace_id` inherits the active W3C trace.
- Keep application startup local-first: no Collector is required when OTLP endpoints are empty.
- `OTEL_ENABLED=true` is the default. Setting it to false disables OTel span/metric/export work for emergency rollback, while request IDs and safe JSON stdout logging remain available.
- Do not add paid or hosted dependencies. The selected backend profile is Collector + Prometheus + Tempo + Loki + Grafana.
- Never put `run_id`, `trace_id`, `span_id`, `step_id`, request paths, prompts, tool arguments, request bodies, exception messages, or credentials in metric attributes.
- Use trace-based metric exemplars to link metrics to traces. Permitted metric dimensions are bounded status/type fields plus sanitized tenant, agent, provider, model, flow, and route-template identifiers.
- Span and log attributes may contain sanitized opaque correlation IDs. Invalid or overlong identifiers are replaced by a stable truncated SHA-256 digest.
- Do not record prompts, completions, tool arguments/results, request bodies, command lines, stdout/stderr, exception text, routing rationale, or reasoning payloads in operational telemetry.
- Set span status from final execution outcome, never from an optimistic pre-execution value.
- New and changed functions, methods, classes, and packages require complete type hints and English Google-style docstrings.
- The story's measured overhead gate is `<5%` on the documented representative 5 ms execution-step workload, using median paired measurements and no live exporter.
- After code changes, run `graphify update .` once before final validation.

## Acceptance Mapping

| Requirement | Evidence |
| --- | --- |
| E11-S1-T1: traces/metrics/logs correlated | W3C middleware tests; request -> run -> step -> model/event/log integration test; trace-based metric exemplar assertion |
| Every run/step/decision traceable | Flow, legacy orchestrator, Agent Runtime, model gateway, reasoning, routing, tool/skill, sandbox, and event tests |
| RED/USE metrics | HTTP rate/error/duration, run/step duration/count, model latency/tokens/cost, eval quality, queue depth, worker utilization |
| E11-S1-T2: exporters and dashboards | Compose profile, Collector pipelines, provisioned Grafana data sources/dashboard, live stack verifier |
| E11-S1-T3: sampling and retention | Typed sampler tests; signal-specific OTLP endpoint tests; Tempo/Prometheus/Loki retention configuration tests |
| No sensitive PII | JSON/OTLP log redaction tests and telemetry payload allowlist tests |
| OTel conventions | SERVER/PRODUCER/CONSUMER span kinds, W3C propagation, route templates, semantic HTTP attributes, resource attributes |
| E0 `<5%` overhead | `scripts/measure_observability_overhead.py` exits successfully only below `0.05` |
| Rollback | `OTEL_ENABLED=false`, documented and tested |
| Story DoD | Integration tests, dashboard smoke verification, documentation, ADR-017, story-scoped quality/security gates |

## Stable Interfaces Introduced

```python
# backend/observability/configuration.py
SignalName = Literal["traces", "metrics", "logs"]
OtelSamplerName = Literal[
    "always_on",
    "always_off",
    "traceidratio",
    "parentbased_always_on",
    "parentbased_always_off",
    "parentbased_traceidratio",
]

def resolve_signal_endpoint(settings: Settings, signal: SignalName) -> str: ...
def build_sampler(name: OtelSamplerName, ratio: float) -> Sampler: ...
```

```python
# backend/observability/context.py
@dataclass(frozen=True)
class CorrelationContext:
    request_id: str = ""
    run_id: str = ""
    step_id: str = ""
    tenant_id: str = ""

def current_correlation_context() -> CorrelationContext: ...
def current_trace_id() -> str: ...
def current_span_id() -> str: ...
def sanitize_identifier(value: str) -> str: ...

@contextmanager
def bind_correlation_context(
    *,
    request_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    tenant_id: str | None = None,
) -> Iterator[CorrelationContext]: ...

def capture_execution_context() -> dict[str, str]: ...

@contextmanager
def attach_execution_context(carrier: Mapping[str, str]) -> Iterator[None]: ...
```

```python
# backend/observability/metrics.py
@dataclass(frozen=True)
class QueueSnapshot:
    pending: int
    running: int
    workers: int
    busy_workers: int

class MetricSink(Protocol):
    def record_http_request(
        self, *, method: str, route: str, status_code: int,
        duration_seconds: float
    ) -> None: ...

    def record_run(
        self, *, tenant_id: str, flow_id: str, status: str,
        duration_seconds: float, input_tokens: int,
        output_tokens: int, cost_usd: float
    ) -> None: ...

    def record_step(
        self, *, tenant_id: str, agent_id: str, status: str,
        duration_seconds: float
    ) -> None: ...

    def record_decision(
        self, *, tenant_id: str, decision_type: str, outcome: str
    ) -> None: ...

    def record_model_call(
        self, *, tenant_id: str, agent_id: str, provider: str, model: str,
        error_code: str, duration_seconds: float, input_tokens: int,
        output_tokens: int, cost_usd: float
    ) -> None: ...

    def record_evaluation(
        self, *, agent_id: str, evaluator_id: str,
        score: float, gate_passed: bool
    ) -> None: ...

    def observe_queue(
        self, *, backend: str, callback: Callable[[], QueueSnapshot]
    ) -> None: ...

def get_metric_sink() -> MetricSink: ...
def set_metric_sink(sink: MetricSink) -> None: ...
```

```python
# backend/observability/runtime.py
@dataclass
class ObservabilityRuntime:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    metric_sink: MetricSink
    log_handlers: tuple[logging.Handler, ...]

    def force_flush(self, timeout_millis: int = 10_000) -> bool: ...
    def shutdown(self) -> None: ...

def configure_observability(
    settings: Settings | None = None,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
    log_exporter: LogExporter | None = None,
    service_name: str | None = None,
    install_global: bool = True,
) -> ObservabilityRuntime: ...

def get_observability_runtime() -> ObservabilityRuntime: ...
def get_tracer(scope: str = "backend.observability") -> trace.Tracer: ...
def get_meter(scope: str = "backend.observability") -> metrics.Meter: ...
def shutdown_observability() -> None: ...
```

`backend.observability.tracing.configure_tracing(...)` remains as a compatibility wrapper over `configure_observability(...)`.

---

## Task 1: Establish ADR-017 and the Typed Three-Signal Runtime

**Files:**

- Create: `docs/v2_platform/decisions/ADR-017-observability-signals-backends.md`
- Create: `backend/observability/configuration.py`
- Create: `backend/observability/context.py`
- Create: `backend/observability/metrics.py`
- Create: `backend/observability/log_correlation.py`
- Create: `backend/observability/runtime.py`
- Create: `backend/tests/observability_helpers.py`
- Create: `backend/tests/unit/observability/test_configuration.py`
- Create: `backend/tests/unit/observability/test_runtime.py`
- Create: `backend/tests/unit/observability/test_log_correlation.py`
- Modify: `docs/v2_platform/decisions/README.md`
- Modify: `backend/config/settings.py`
- Modify: `backend/observability/tracing.py`
- Modify: `backend/observability/__init__.py`
- Modify: `backend/api/main.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.txt`

**Interfaces:**

- Consumes: `Settings`, OTel SDK provider/exporter interfaces, existing `configure_tracing`.
- Produces: all stable interfaces listed above, explicit sampler construction, signal-specific endpoints, trace-based exemplars, structured/redacted logging, lifecycle shutdown.

- [ ] Create ADR-017 with status `Accepted`, date `2026-08-15`, and story `E11-S1`. Record these decisions:

  - Application signals use OTLP/HTTP through a Collector gateway.
  - Tempo, Prometheus, Loki, and Grafana are the default self-hosted OSS profile.
  - Metrics link to traces through exemplars, not high-cardinality ID labels.
  - JSON logs and OTel logs share the same redaction filter.
  - Default retention is traces `168h`, metrics `15d`, logs `168h`.
  - Sampling defaults to `parentbased_traceidratio` with ratio `1.0`.
  - Empty exporter endpoints mean local no-export operation.
  - `OTEL_ENABLED=false` is the emergency rollback.
  - Alert delivery and comprehensive runbooks remain E11-S4.
  - Rejected alternatives: paid SaaS as a required backend, direct application-to-each-backend exporters, trace/run IDs as metric labels.

- [ ] Add RED configuration tests:

```python
@pytest.mark.parametrize(
    ("name", "expected_type"),
    [
        ("always_on", StaticSampler),
        ("always_off", StaticSampler),
        ("traceidratio", TraceIdRatioBased),
        ("parentbased_always_on", ParentBased),
        ("parentbased_always_off", ParentBased),
        ("parentbased_traceidratio", ParentBased),
    ],
)
def test_build_sampler_supports_the_documented_vocabulary(
    name: OtelSamplerName, expected_type: type[Sampler]
) -> None:
    sampler = build_sampler(name, 0.25)
    assert isinstance(sampler, expected_type)


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        ("traces", "http://collector:4318/v1/traces"),
        ("metrics", "http://collector:4318/v1/metrics"),
        ("logs", "http://collector:4318/v1/logs"),
    ],
)
def test_base_otlp_endpoint_expands_per_signal(
    signal: SignalName, expected: str
) -> None:
    settings = Settings(otel_exporter_otlp_endpoint="http://collector:4318")
    assert resolve_signal_endpoint(settings, signal) == expected


def test_signal_specific_endpoint_wins() -> None:
    settings = Settings(
        otel_exporter_otlp_endpoint="http://collector:4318",
        otel_exporter_otlp_metrics_endpoint="http://metrics:4318/custom",
    )
    assert resolve_signal_endpoint(settings, "metrics") == "http://metrics:4318/custom"


def test_retention_and_sampling_are_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(autodev_observability_trace_retention="forever")
    with pytest.raises(ValidationError):
        Settings(otel_traces_sampler="vendor_magic")
```

- [ ] Run the RED tests:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_configuration.py -q
```

Expected: collection fails because `backend.observability.configuration` and the new settings fields do not exist.

- [ ] Add these settings with typed defaults:

```python
OtelSamplerName = Literal[
    "always_on",
    "always_off",
    "traceidratio",
    "parentbased_always_on",
    "parentbased_always_off",
    "parentbased_traceidratio",
]

otel_enabled: bool = True
otel_service_name: str = "autodev-backend"
otel_exporter_otlp_endpoint: str = ""
otel_exporter_otlp_traces_endpoint: str = ""
otel_exporter_otlp_metrics_endpoint: str = ""
otel_exporter_otlp_logs_endpoint: str = ""
otel_traces_sampler: OtelSamplerName = "parentbased_traceidratio"
otel_traces_sampler_arg: float = Field(default=1.0, ge=0.0, le=1.0)
otel_metric_export_interval_ms: int = Field(default=5_000, ge=1_000)
autodev_observability_trace_retention: str = Field(
    default="168h", pattern=r"^[1-9]\d*(?:s|m|h|d|w)$"
)
autodev_observability_metric_retention: str = Field(
    default="15d", pattern=r"^[1-9]\d*(?:s|m|h|d|w)$"
)
autodev_observability_log_retention: str = Field(
    default="168h", pattern=r"^[1-9]\d*(?:s|m|h|d|w)$"
)
```

Add every OTLP endpoint field to `_SECRET_FIELDS` so credentials embedded in a URL cannot leak through `/features`.

- [ ] Implement explicit endpoint and sampler resolution:

```python
_SIGNAL_PATHS: dict[SignalName, str] = {
    "traces": "/v1/traces",
    "metrics": "/v1/metrics",
    "logs": "/v1/logs",
}


def resolve_signal_endpoint(settings: Settings, signal: SignalName) -> str:
    specific = getattr(settings, f"otel_exporter_otlp_{signal}_endpoint").strip()
    if specific:
        return specific
    base = settings.otel_exporter_otlp_endpoint.strip().rstrip("/")
    if not base:
        return ""
    if base.endswith(tuple(_SIGNAL_PATHS.values())):
        return base if base.endswith(_SIGNAL_PATHS[signal]) else ""
    return f"{base}{_SIGNAL_PATHS[signal]}"


def build_sampler(name: OtelSamplerName, ratio: float) -> Sampler:
    roots: dict[str, Sampler] = {
        "always_on": ALWAYS_ON,
        "always_off": ALWAYS_OFF,
        "traceidratio": TraceIdRatioBased(ratio),
    }
    if name in roots:
        return roots[name]
    parent_roots = {
        "parentbased_always_on": ALWAYS_ON,
        "parentbased_always_off": ALWAYS_OFF,
        "parentbased_traceidratio": TraceIdRatioBased(ratio),
    }
    return ParentBased(parent_roots[name])
```

- [ ] Add RED context, log, and runtime tests:

```python
def test_active_span_and_bound_domain_context_are_correlated() -> None:
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


def test_json_and_otlp_logs_share_redaction_and_correlation() -> None:
    stream = io.StringIO()
    with capture_observability(log_stream=stream) as capture:
        with bind_correlation_context(run_id="run-1", tenant_id="tenant-1"):
            with get_tracer().start_as_current_span("log-test"):
                logging.getLogger("backend.test").info(
                    "Authorization: Bearer secret-value user@example.com",
                    extra={"step_id": "step-1"},
                )
        capture.runtime.force_flush()

    rendered = stream.getvalue()
    assert '"run_id":"run-1"' in rendered
    assert '"tenant_id":"tenant-1"' in rendered
    assert '"trace_id":"' in rendered
    assert "secret-value" not in rendered
    assert "user@example.com" not in rendered
    assert all(
        "secret-value" not in str(record.log_record.body)
        for record in capture.log_exporter.get_finished_logs()
    )


def test_disabled_runtime_installs_no_export_processors() -> None:
    runtime = configure_observability(
        Settings(otel_enabled=False), install_global=False
    )
    assert runtime.metric_sink.__class__.__name__ == "NoopMetricSink"
```

- [ ] Run the RED runtime tests:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_runtime.py backend/tests/unit/observability/test_log_correlation.py -q
```

Expected: imports or assertions fail because the runtime, context binding, JSON formatter, and common redaction filter are absent.

- [ ] Implement `CorrelationContext`, nested `ContextVar` binding, W3C carrier capture/attach, lowercase 32/16-character trace/span formatting, and identifier sanitization. Use this sanitization rule:

```python
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")


def sanitize_identifier(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if _SAFE_IDENTIFIER.fullmatch(normalized):
        return normalized
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"sha256:{digest}"
```

- [ ] Implement one mutating `TelemetryRedactionFilter` shared by the JSON and OTel logging handlers. It must redact:

  - keys containing `authorization`, `cookie`, `credential`, `password`, `secret`, `token`, `api_key`, `access_key`, or `private_key`;
  - bearer tokens and common API-key forms in strings;
  - email addresses;
  - values recursively inside mappings and sequences.

`JsonLogFormatter` must emit only timestamp, severity, logger, message, exception type/redacted stack, correlation fields, and the allowlisted operational extras `event`, `method`, `route`, `status`, `duration_s`, `error_code`.

- [ ] Implement `MetricSink`, `NoopMetricSink`, and `OtelMetricSink` with these exact instruments:

| OTel instrument | Kind | Unit | Dimensions |
| --- | --- | --- | --- |
| `http.server.request.duration` | histogram | `s` | method, route, status code |
| `autodev.run.duration` | histogram | `s` | tenant, flow, final status |
| `autodev.run.step.duration` | histogram | `s` | tenant, agent, final status |
| `autodev.run.step.count` | counter | `{step}` | tenant, agent, final status |
| `autodev.decision.count` | counter | `{decision}` | tenant, decision type, outcome |
| `gen_ai.client.operation.duration` | histogram | `s` | tenant, agent, provider, model, error code |
| `autodev.model.tokens` | counter | `{token}` | tenant, agent, provider, model, token type |
| `autodev.model.cost_usd` | counter | `USD` | tenant, agent, provider, model |
| `autodev.agent.quality_ratio` | histogram | `1` | agent, evaluator, gate result |
| `autodev.queue.jobs` | observable gauge | `{job}` | backend, state |
| `autodev.worker.utilization` | observable gauge | `1` | backend |

Construct `MeterProvider` with `TraceBasedExemplarFilter()`.

- [ ] Implement `ObservabilityRuntime`. Use `SimpleSpanProcessor` and `SimpleLogRecordProcessor` only for injected test exporters. Production uses `BatchSpanProcessor`, `PeriodicExportingMetricReader`, and `BatchLogRecordProcessor` with OTLP/HTTP exporters. Resolve `service.version` without importing `backend.api.main`:

```python
def _service_version() -> str:
    try:
        return importlib.metadata.version("autodev-backend")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


resource = Resource.create(
    {
        "service.name": service_name or settings.otel_service_name,
        "service.version": _service_version(),
        "service.instance.id": str(uuid.uuid4()),
        "deployment.environment.name": settings.autodev_profile,
    }
)
```

- [ ] Make `configure_tracing(...)` delegate to `configure_observability(...)` without breaking its current signature. Make `get_tracer()` delegate to the owned runtime.

- [ ] Update FastAPI lifespan to configure once and always shut down in `finally`. Preserve the existing production-only infrastructure initialization in this task; queue observation is activated after `stats()` exists in Task 4:

```python
runtime = configure_observability(settings)
try:
    if settings.autodev_profile == "prod":
        get_cache(settings)
        get_lock_manager(settings)
        get_artifact_store(settings)
        get_queue(settings)
    get_runtime_config_service().apply_to_environment()
    get_orchestrator()
    yield
finally:
    shutdown_observability()
```

- [ ] Keep identical OTel dependency bounds in `backend/requirements.txt` and `backend/pyproject.toml`:

```toml
"opentelemetry-api>=1.28",
"opentelemetry-sdk>=1.28",
"opentelemetry-exporter-otlp-proto-http>=1.28",
```

- [ ] Run the Task 1 tests:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_configuration.py backend/tests/unit/observability/test_runtime.py backend/tests/unit/observability/test_log_correlation.py backend/tests/unit/config/test_settings.py -q
```

Expected: all pass.

- [ ] Commit:

```bash
git add backend/config/settings.py backend/observability backend/api/main.py backend/pyproject.toml backend/requirements.txt backend/tests/observability_helpers.py backend/tests/unit/observability docs/v2_platform/decisions/ADR-017-observability-signals-backends.md docs/v2_platform/decisions/README.md
git commit -m "feat(observability): establish three-signal otel runtime"
```

---

## Task 2: Correlate HTTP Requests, JSON Logs, and RED Metrics

**Files:**

- Modify: `backend/observability/middleware.py`
- Modify: `backend/tests/unit/observability/test_observability.py`
- Create: `backend/tests/unit/observability/test_http_correlation.py`

**Interfaces:**

- Consumes: `get_tracer()`, `get_metric_sink()`, `bind_correlation_context()`, W3C propagator.
- Produces: SERVER spans parented from incoming `traceparent`, safe route-template RED metrics, correlated request logs, echoed request ID.
- Preserves: `MetricsRegistry`, `get_registry()`, `attach()`, and `GET /metrics`.

- [ ] Add RED tests for remote-parent extraction, incoming request-ID echo, route cardinality, exemplar correlation, and secret-free error handling:

```python
def test_server_span_uses_incoming_w3c_parent() -> None:
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    parent_span_id = "b7ad6b7169203331"
    with capture_observability() as capture:
        response = TestClient(_make_app()).get(
            "/items/42",
            headers={
                "traceparent": f"00-{trace_id}-{parent_span_id}-01",
                "x-request-id": "request-upstream-1",
            },
        )

    server = next(span for span in capture.spans if span.kind is SpanKind.SERVER)
    assert f"{server.context.trace_id:032x}" == trace_id
    assert server.parent is not None
    assert f"{server.parent.span_id:016x}" == parent_span_id
    assert response.headers["x-request-id"] == "request-upstream-1"


def test_http_metric_uses_route_template_and_trace_exemplar() -> None:
    with capture_observability() as capture:
        client = TestClient(_make_app())
        client.get("/items/customer-a")
        client.get("/items/customer-b")
        capture.runtime.force_flush()
        points = capture.metric_points("http.server.request.duration")

    assert {point.attributes["http.route"] for point in points} == {"/items/{item_id}"}
    assert "customer-a" not in repr(points)
    assert "customer-b" not in repr(points)
    assert any(point.exemplars for point in points)


def test_http_failure_never_records_raw_exception_text() -> None:
    secret = "sk-sensitive-value"
    with capture_observability() as capture:
        with pytest.raises(RuntimeError):
            TestClient(_make_failing_app(secret), raise_server_exceptions=True).get("/boom")

    server = next(span for span in capture.spans if span.kind is SpanKind.SERVER)
    assert server.status.status_code is StatusCode.ERROR
    assert server.status.description == "internal_error"
    assert secret not in repr(server.attributes)
    assert secret not in repr(server.events)
```

- [ ] Run RED:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_http_correlation.py backend/tests/unit/observability/test_observability.py -q
```

Expected: the parent-span assertion fails, incoming request IDs are replaced, raw paths appear, and no OTel histogram/exemplar exists.

- [ ] Refactor `RequestTracingMiddleware.__call__` to:

  1. Normalize ASGI headers into a string carrier.
  2. Accept a safe incoming `X-Request-ID`, otherwise generate UUID4.
  3. Extract the W3C parent with `propagate.extract(carrier)`.
  4. Start a `SpanKind.SERVER` span with `record_exception=False` and `set_status_on_exception=False`.
  5. Bind `request_id`.
  6. After routing, use `scope["route"].path`; use `"_unmatched"` when absent.
  7. Update the span name to `"{method} {route}"`.
  8. Record the HTTP histogram before the span ends so the data point receives an exemplar.
  9. Emit one safe structured completion log while the span is active.
  10. On exceptions, set only `Status(ERROR, "internal_error")`, record status `500`, and re-raise.
  11. Replace any pre-existing response `x-request-id` header rather than appending a duplicate.

Core shape:

```python
parent_context = propagate.extract(carrier)
with bind_correlation_context(request_id=request_id):
    with get_tracer().start_as_current_span(
        f"{method} pending-route",
        context=parent_context,
        kind=SpanKind.SERVER,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            await self._app(scope, receive, send_with_header)
        except BaseException:
            response_status = 500
            span.set_status(Status(StatusCode.ERROR, "internal_error"))
            raise
        finally:
            route = _route_template(scope)
            elapsed = time.perf_counter() - started
            span.update_name(f"{method} {route}")
            span.set_attributes(
                _safe_http_attributes(
                    method=method,
                    route=route,
                    status_code=response_status,
                    request_id=request_id,
                )
            )
            get_metric_sink().record_http_request(
                method=method,
                route=route,
                status_code=response_status,
                duration_seconds=elapsed,
            )
            logger.info(
                "request completed",
                extra={
                    "event": "http.request.completed",
                    "request_id": request_id,
                    "method": method,
                    "route": route,
                    "status": response_status,
                    "duration_s": round(elapsed, 6),
                },
            )
```

Here `_safe_http_attributes(method, route, response_status, request_id)` is an exact helper implemented in this task and returns only `http.request.method`, `http.route`, `http.response.status_code`, and `autodev.request_id`.

Continue updating the legacy registry for `/metrics`, but pass the route template instead of the raw URL path.

- [ ] Run Task 2 tests:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_http_correlation.py backend/tests/unit/observability/test_observability.py -q
```

Expected: all pass, including existing `/metrics` compatibility tests.

- [ ] Commit:

```bash
git add backend/observability/middleware.py backend/tests/unit/observability/test_observability.py backend/tests/unit/observability/test_http_correlation.py
git commit -m "feat(observability): correlate http traces logs and metrics"
```

---

## Task 3: Instrument the Critical Run Path and Decision Trace

**Files:**

- Modify: `backend/observability/tracing.py`
- Modify: `backend/orchestrator/service.py`
- Modify: `backend/flows/engine.py`
- Modify: `backend/flows/activation.py`
- Modify: `backend/agents/runtime.py`
- Modify: `backend/llm/gateway.py`
- Modify: `backend/events/runtime.py`
- Modify: `backend/reasoning/service.py`
- Modify: `backend/routing/service.py`
- Modify: `backend/evals/service.py`
- Modify: `backend/validation/sandbox.py`
- Modify: `backend/tests/unit/observability/test_model_tracing.py`
- Modify: `backend/tests/unit/events/test_event_catalog.py`
- Modify: `backend/tests/unit/flows/test_flows_engine.py`
- Modify: `backend/tests/unit/agents/test_agent_runtime_model_gateway.py`
- Create: `backend/tests/unit/observability/test_execution_tracing.py`
- Create: `backend/tests/integration/observability/__init__.py`
- Create: `backend/tests/integration/observability/test_signal_correlation.py`

**Interfaces:**

```python
@dataclass
class RunTrace:
    status: str = "running"
    error_code: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def finish(
        self, *, status: str, error_code: str = "",
        input_tokens: int = 0, output_tokens: int = 0,
        cost_usd: float = 0.0
    ) -> None: ...


@dataclass
class StepTrace:
    status: str = "running"
    error_code: str = ""

    def finish(self, *, status: str, error_code: str = "") -> None: ...


@contextmanager
def trace_run(
    *, run_id: str, tenant_id: str, flow_id: str
) -> Iterator[RunTrace]: ...

@contextmanager
def trace_run_step(
    *, run_id: str, step_id: str, agent: str,
    status: str = "running", tenant_id: str = ""
) -> Iterator[StepTrace]: ...

@contextmanager
def trace_dependency(
    *, kind: Literal["tool", "skill", "sandbox"], name: str,
    run_id: str = "", tenant_id: str = ""
) -> Iterator[StepTrace]: ...

def record_decision(
    *, name: str, outcome: str, tenant_id: str = "",
    run_id: str = "", attributes: Mapping[str, AttributeValue] | None = None
) -> None: ...
```

`trace_model_call(...)` gains optional `run_id: str = ""` and `tenant_id: str = ""` parameters.

- [ ] Add RED execution tests:

```python
def test_flow_emits_final_run_and_step_statuses(tmp_path: Path) -> None:
    with capture_observability() as capture:
        engine, callables = _engine(tmp_path)
        _register_linear_callables(callables)
        engine.registry.register_raw(_linear_flow())
        result = engine.start_run(
            "autodev/flow-linear",
            input={"task": "ship"},
            tenant_id="tenant-1",
        )
        capture.runtime.force_flush()

    run_span = next(span for span in capture.spans if span.name == "autodev.run")
    step_spans = [
        span for span in capture.spans
        if span.name.startswith("autodev.run.step.")
    ]
    assert run_span.attributes["autodev.run_id"] == result.run_id
    assert run_span.attributes["autodev.status"] == "completed"
    assert step_spans
    assert all(span.attributes["autodev.status"] == "completed" for span in step_spans)
    assert all(span.parent is not None for span in step_spans)
    assert all(span.parent.span_id == run_span.context.span_id for span in step_spans)


def test_model_span_carries_runtime_context_without_prompt_content() -> None:
    secret_prompt = "sk-sensitive-prompt"
    with capture_observability() as capture:
        gateway, _ = _gateway(
            m=StubModelOutput(
                text="done",
                usage=TokenUsage(4, 6),
                cost=EstimatedCost(0.5),
            )
        )
        runtime = AgentRuntime(
            gateway=gateway,
            model_config=ModelConfig(provider="stub", name="m"),
        )
        result = runtime.run(
            _manifest(),
            _payload(),
            lambda ctx: {
                "schemaVersion": "1.0.0",
                "result": ctx.call_llm(secret_prompt),
            },
            run_id="run-1",
            tenant_id="tenant-1",
        )

    model_span = next(span for span in capture.spans if span.name == "autodev.model.call")
    assert result.status == "completed"
    assert model_span.attributes["autodev.run_id"] == "run-1"
    assert model_span.attributes["autodev.tenant_id"] == "tenant-1"
    assert secret_prompt not in repr(model_span.attributes)
    assert secret_prompt not in repr(model_span.events)


def test_event_envelope_inherits_active_w3c_trace_id() -> None:
    bus = InMemoryEventBus()
    with capture_observability():
        with get_tracer().start_as_current_span("producer") as span:
            emit_event(
                "flow.run.started",
                tenant_id="tenant-1",
                partition_key="run-1",
                data={"flowId": "autodev/test", "flowVersion": "1.0.0"},
                bus=bus,
            )
            expected = f"{span.get_span_context().trace_id:032x}"

    assert bus.replay("run-1")[0].traceId == expected
```

In the existing reasoning-selection test fixture, add this contract assertion while an OTel span is active:

```python
with capture_observability():
    with get_tracer().start_as_current_span("operational") as span:
        w3c_trace_id = f"{span.get_span_context().trace_id:032x}"
        result = asyncio.run(service.run(run_input))

assert result.output.trace_id
assert result.output.trace_id != w3c_trace_id
assert len(result.output.trace_id) == 36
```

- [ ] Run RED:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_execution_tracing.py backend/tests/unit/flows/test_flows_engine.py backend/tests/unit/agents/test_agent_runtime_model_gateway.py backend/tests/unit/events/test_event_catalog.py -q
```

Expected: missing `trace_run`, missing final status/parent correlation, missing run/tenant model attributes, and empty `EventEnvelope.traceId`.

- [ ] Implement the run/step/dependency context managers with these rules:

  - bind sanitized domain context before opening the span;
  - use `record_exception=False` and `set_status_on_exception=False`;
  - on an uncaught exception, record only `unhandled_error`;
  - finalize duration, attributes, metric, and structured completion log before ending the span;
  - record metrics while the span is active for exemplar creation;
  - never accept arbitrary exception text or payload mappings as telemetry attributes.

- [ ] Wrap `OrchestratorService.handle_message()` in `trace_run(...)`. Move its `flow.run.started` and `flow.run.completed` bus emissions inside the run span. Mark completion only after persistence succeeds.

- [ ] In `FlowEngine.start_run()`:

  - create the durable run first;
  - enter `trace_run(run_id, tenant_id, flow_id)`;
  - emit `flow.run.started` inside that span;
  - call `_run_loop()` directly when `execute=True` to avoid a duplicate run span;
  - finalize from the returned `FlowRunRecord`.

In `execute_run()`, open one run span around `_run_loop()` for resumed/deferred execution.

- [ ] In `NodeActivationMixin._activate_node()`, use the mutable `StepTrace` and set `completed`, `failed`, or the stable stop reason before leaving the context. Remove the fixed `"running"` final attribute.

- [ ] In `AgentRuntime.run()`, bind run/tenant context for the complete method and open `autodev.agent.run`. Trace the actual handler duration as one `run-handler` step; remove the empty instantaneous `"running"` span. Preserve returned timeline contracts and stable failure reasons.

- [ ] Wrap `AgentRuntimeContext.call_tool()` and `call_skill()` with `trace_dependency()`. Record only the granted tool/skill identifier, kind, status, run ID, and tenant ID.

- [ ] Extend `_model_trace(...)` and both complete/stream call sites to read `run_id` and `tenant_id` from `ExecutionMetadata.attributes`. Finalize the model metric from the same safe measurements used by the span.

- [ ] Wrap `SandboxRunner.run()` with `trace_dependency(kind="sandbox", name="validation")`. Set only backend, skipped/success/failed status, and a stable error code. Never attach command, working directory, stdout, or stderr.

- [ ] Change `emit_event()` defaulting:

```python
effective_trace_id = trace_id or current_trace_id()
envelope = make_envelope(
    type_,
    tenant_id=tenant_id,
    partition_key=partition_key,
    data=data,
    subject=subject,
    trace_id=effective_trace_id,
)
```

An explicit `trace_id` continues to win.

- [ ] Make operational decision telemetry unconditional while preserving optional replay callbacks:

  - `ReasoningService` passes an internal tee callback to `ReasoningEngine`; it calls `record_decision()` and then the caller's original `on_event`.
  - `RoutingService._emit()` records router/selector decision spans and metrics before invoking its callback.
  - Never attach task text, messages, rationale, paths, prompts, tool arguments, or full event payloads.
  - Allowed decision attributes are strategy ID, selection source, task type, intent, agent ID, model ID, and gate result.
  - `EvaluationService.run_offline()` records each `metrics.quality` entry with `record_evaluation()` after durable persistence succeeds.

- [ ] Add the end-to-end integration test. It must issue a request carrying `traceparent`, execute a real `AgentRuntime` with `StubModelProvider`, emit a canonical event, and log a completion record. Assert:

```python
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
assert "sk-sensitive-prompt" not in repr(capture.all_signals())
```

- [ ] Run Task 3 tests:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_execution_tracing.py backend/tests/unit/observability/test_model_tracing.py backend/tests/unit/llm/test_model_gateway.py backend/tests/unit/flows/test_flows_engine.py backend/tests/unit/agents/test_agent_runtime_model_gateway.py backend/tests/unit/events/test_event_catalog.py backend/tests/unit/reasoning backend/tests/unit/routing backend/tests/unit/evals backend/tests/integration/observability/test_signal_correlation.py -q
```

Expected: all pass.

- [ ] Commit:

```bash
git add backend/observability/tracing.py backend/orchestrator/service.py backend/flows backend/agents/runtime.py backend/llm/gateway.py backend/events/runtime.py backend/reasoning/service.py backend/routing/service.py backend/evals/service.py backend/validation/sandbox.py backend/tests/unit backend/tests/integration/observability
git commit -m "feat(observability): trace runs steps models and decisions"
```

---

## Task 4: Propagate Context Across Jobs and Export Queue/Worker USE Metrics

**Files:**

- Modify: `backend/jobs/queue.py`
- Modify: `backend/api/main.py`
- Modify: `backend/tests/unit/jobs/test_job_queue.py`
- Modify: `backend/tests/unit/jobs/test_queue_gaps.py`
- Create: `backend/tests/unit/jobs/test_job_observability.py`

**Interfaces:**

```python
# Added to AbstractJobQueue, InProcessJobQueue, and RedisJobQueue.
def stats(self) -> QueueSnapshot: ...
```

- [ ] Add a concrete bounded wait helper and RED tests:

```python
def _wait_for_stats(
    queue: AbstractJobQueue,
    predicate: Callable[[QueueSnapshot], bool],
    *,
    timeout_seconds: float = 1.0,
) -> QueueSnapshot:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        snapshot = queue.stats()
        if predicate(snapshot):
            return snapshot
        time.sleep(0.01)
    raise AssertionError("queue stats did not reach the expected state")


def _wait_for_job(
    queue: AbstractJobQueue,
    job_id: str,
    *,
    timeout_seconds: float = 1.0,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        record = queue.get(job_id)
        if record["status"] in {"done", "error"}:
            return record
        time.sleep(0.01)
    raise AssertionError("job did not reach a terminal state")


def test_inprocess_queue_reports_pending_running_and_worker_use() -> None:
    release = threading.Event()
    register_handler("blocking")(lambda payload: release.wait(timeout=1))
    queue = InProcessJobQueue(max_workers=2)

    queue.enqueue("blocking", {})
    snapshot = _wait_for_stats(queue, lambda value: value.running == 1)

    assert snapshot.workers == 2
    assert snapshot.busy_workers == 1
    assert snapshot.pending >= 0
    release.set()


def test_job_consumer_continues_the_producer_trace() -> None:
    completed = threading.Event()
    register_handler("observed")(lambda payload: completed.set())
    queue = InProcessJobQueue(max_workers=1)

    with capture_observability() as capture:
        with bind_correlation_context(run_id="run-1", tenant_id="tenant-1"):
            with get_tracer().start_as_current_span("request"):
                queue.enqueue("observed", {})
        assert completed.wait(timeout=1)

    producer = next(span for span in capture.spans if span.name == "autodev.job.enqueue")
    consumer = next(span for span in capture.spans if span.name == "autodev.job.execute")
    assert producer.kind is SpanKind.PRODUCER
    assert consumer.kind is SpanKind.CONSUMER
    assert consumer.parent is not None
    assert consumer.parent.span_id == producer.context.span_id
    assert consumer.attributes["autodev.run_id"] == "run-1"
    assert consumer.attributes["autodev.tenant_id"] == "tenant-1"


def test_job_context_is_internal_not_returned_as_payload() -> None:
    queue = InProcessJobQueue(max_workers=1)
    job_id = queue.enqueue("echo", {"secret": "payload-remains-domain-data"})
    record = _wait_for_job(queue, job_id)
    assert set(record) == {"job_id", "job_type", "status", "result", "error"}
```

- [ ] Run RED:

```bash
source .venv/bin/activate && pytest backend/tests/unit/jobs/test_job_observability.py backend/tests/unit/jobs/test_job_queue.py backend/tests/unit/jobs/test_queue_gaps.py -q
```

Expected: `stats()` is absent and producer/consumer spans are missing.

- [ ] Add `AbstractJobQueue.stats() -> QueueSnapshot`.

For `InProcessJobQueue`:

- retain `_max_workers`;
- count pending/running statuses under `_lock`;
- report `busy_workers == running`;
- keep trace/correlation carriers in a separate `_execution_contexts` dictionary so `get()` remains unchanged;
- delete the carrier after terminal completion.

For `RedisJobQueue`:

- use `LLEN autodev:jobs:pending` for pending count;
- track current-process `_busy_workers` under a lock;
- report `workers=1` only when its worker thread is enabled;
- store internal `otel_traceparent`, `otel_tracestate`, `otel_baggage`, `correlation_request_id`, `correlation_run_id`, and `correlation_tenant_id` hash fields;
- continue returning only the documented public job fields from `get()`.

- [ ] After all queue implementations expose `stats()`, register the callback in FastAPI lifespan without changing the existing backend selection:

```python
queue = get_queue(settings)
runtime.metric_sink.observe_queue(
    backend=settings.autodev_job_backend,
    callback=queue.stats,
)
```

For the local profile this initializes the existing in-process singleton; for production it reuses the Redis singleton already initialized by the production infrastructure block.

- [ ] Instrument queue transitions:

```python
with get_tracer().start_as_current_span(
    "autodev.job.enqueue",
    kind=SpanKind.PRODUCER,
    record_exception=False,
    set_status_on_exception=False,
):
    carrier = capture_execution_context()
    # Persist carrier in the queue's internal context store, not the job payload.

with attach_execution_context(carrier):
    with get_tracer().start_as_current_span(
        "autodev.job.execute",
        kind=SpanKind.CONSUMER,
        record_exception=False,
        set_status_on_exception=False,
    ):
        handler(payload)
```

Never attach job payload, result, or raw error text.

- [ ] Add a metric-reader assertion:

```python
def test_queue_and_worker_observable_gauges_use_snapshot_callback() -> None:
    queue = InProcessJobQueue(max_workers=4)
    with capture_observability() as capture:
        get_metric_sink().observe_queue(
            backend="inprocess",
            callback=queue.stats,
        )
        capture.runtime.force_flush()

    assert capture.gauge_value(
        "autodev.queue.jobs", backend="inprocess", state="pending"
    ) == 0
    assert capture.gauge_value(
        "autodev.worker.utilization", backend="inprocess"
    ) == 0.0
```

- [ ] Run Task 4 tests:

```bash
source .venv/bin/activate && pytest backend/tests/unit/jobs/test_job_observability.py backend/tests/unit/jobs/test_job_queue.py backend/tests/unit/jobs/test_queue_gaps.py -q
```

Expected: all pass.

- [ ] Commit:

```bash
git add backend/jobs/queue.py backend/api/main.py backend/tests/unit/jobs
git commit -m "feat(observability): propagate job traces and expose use metrics"
```

---

## Task 5: Provision the OSS Signal Backends, Retention, and Dashboard

**Files:**

- Create: `infrastructure/observability/otel-collector.yaml`
- Create: `infrastructure/observability/prometheus.yaml`
- Create: `infrastructure/observability/prometheus-rules.yml`
- Create: `infrastructure/observability/tempo.yaml`
- Create: `infrastructure/observability/loki.yaml`
- Create: `infrastructure/observability/grafana/provisioning/datasources/datasources.yaml`
- Create: `infrastructure/observability/grafana/provisioning/dashboards/dashboards.yaml`
- Create: `infrastructure/observability/grafana/dashboards/autodev-overview.json`
- Create: `scripts/verify_observability_stack.py`
- Create: `backend/tests/unit/observability/test_observability_assets.py`
- Modify: `infrastructure/docker-compose.yml`
- Modify: `Makefile`

**Interfaces:**

- Application OTLP/HTTP: `otel-collector:4318`.
- Collector Prometheus exporter: `otel-collector:9464`.
- Prometheus: host `9090`.
- Tempo query API: host `3200`.
- Loki query API: host `3100`.
- Grafana: host `3001`.
- Compose profile: `observability`.

- [ ] Add RED asset tests with concrete repository paths:

```python
ROOT = Path(__file__).resolve().parents[4]
OBSERVABILITY = ROOT / "infrastructure" / "observability"
COLLECTOR = OBSERVABILITY / "otel-collector.yaml"
PROMETHEUS = OBSERVABILITY / "prometheus.yaml"
TEMPO = OBSERVABILITY / "tempo.yaml"
LOKI = OBSERVABILITY / "loki.yaml"
DASHBOARD = OBSERVABILITY / "grafana" / "dashboards" / "autodev-overview.json"
COMPOSE = ROOT / "infrastructure" / "docker-compose.yml"


def test_collector_routes_all_three_signals() -> None:
    config = yaml.safe_load(COLLECTOR.read_text(encoding="utf-8"))
    pipelines = config["service"]["pipelines"]
    assert pipelines["traces"]["exporters"] == ["otlphttp/tempo"]
    assert pipelines["metrics"]["exporters"] == ["prometheus"]
    assert pipelines["logs"]["exporters"] == ["otlphttp/loki"]


def test_dashboard_contains_required_operational_panels() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {
        "HTTP Request Rate",
        "HTTP Error Ratio",
        "HTTP Latency p95",
        "Run and Step Latency p95",
        "Model Latency p95",
        "Cost by Tenant",
        "Tokens by Tenant",
        "Agent Quality",
        "Queue Depth",
        "Worker Utilization",
    } <= titles


def test_retention_is_operator_configurable() -> None:
    assert "${AUTODEV_OBSERVABILITY_TRACE_RETENTION}" in TEMPO.read_text(encoding="utf-8")
    assert "${AUTODEV_OBSERVABILITY_LOG_RETENTION}" in LOKI.read_text(encoding="utf-8")
    assert "AUTODEV_OBSERVABILITY_METRIC_RETENTION" in COMPOSE.read_text(encoding="utf-8")
```

- [ ] Run RED:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_observability_assets.py -q
```

Expected: all asset paths are missing.

- [ ] Add the Collector configuration:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 384
  batch:
    timeout: 1s
    send_batch_size: 1024

exporters:
  otlphttp/tempo:
    endpoint: http://tempo:4318
  prometheus:
    endpoint: 0.0.0.0:9464
    enable_open_metrics: true
    without_units: true
  otlphttp/loki:
    endpoint: http://loki:3100/otlp

extensions:
  health_check:
    endpoint: 0.0.0.0:13133

service:
  extensions: [health_check]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/tempo]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/loki]
```

- [ ] Add single-node local-storage Tempo and Loki configs. Tempo's compactor uses `${AUTODEV_OBSERVABILITY_TRACE_RETENTION}`. Loki's `limits_config.retention_period` uses `${AUTODEV_OBSERVABILITY_LOG_RETENTION}` and enables compactor retention. Start both images with `-config.expand-env=true` so the checked environment strings are actually resolved.

- [ ] Configure Prometheus to:

  - scrape `otel-collector:9464`;
  - load `/etc/prometheus/prometheus-rules.yml`;
  - run with `--enable-feature=exemplar-storage`;
  - use `${AUTODEV_OBSERVABILITY_METRIC_RETENTION:-15d}` as `--storage.tsdb.retention.time`.

Add these recording rules, not alert delivery:

```yaml
groups:
  - name: autodev-observability
    rules:
      - record: autodev:http_error_ratio:rate5m
        expr: |
          sum(rate(http_server_request_duration_count{http_response_status_code=~"5.."}[5m]))
          /
          clamp_min(sum(rate(http_server_request_duration_count[5m])), 1)
      - record: autodev:http_latency_p95_seconds:rate5m
        expr: |
          histogram_quantile(
            0.95,
            sum by (le, http_route) (
              rate(http_server_request_duration_bucket[5m])
            )
          )
```

E11-S4 adds alert rules, Alertmanager receivers, and per-alert runbooks to this same file/profile.

- [ ] Provision Grafana data sources with stable UIDs `prometheus`, `tempo`, and `loki`. Configure:

  - Tempo service-map metrics from Prometheus;
  - Tempo trace-to-logs link to Loki;
  - Loki derived field matching JSON `"trace_id":"([0-9a-f]{32})"` and linking to Tempo;
  - Prometheus exemplars linking `trace_id` to Tempo.

- [ ] Build `autodev-overview.json` with the ten required panels and these query families:

```promql
sum(rate(http_server_request_duration_count[5m])) by (http_route)
autodev:http_error_ratio:rate5m
autodev:http_latency_p95_seconds:rate5m
histogram_quantile(0.95, sum by (le, autodev_agent_id) (
  rate(autodev_run_step_duration_bucket[5m])
))
histogram_quantile(0.95, sum by (le, gen_ai_request_model) (
  rate(gen_ai_client_operation_duration_bucket[5m])
))
sum(increase(autodev_model_cost_usd_total[$__range])) by (autodev_tenant_id)
sum(increase(autodev_model_tokens_total[$__range])) by (
  autodev_tenant_id, autodev_token_type
)
sum(autodev_agent_quality_ratio_sum) by (autodev_agent_id)
/
clamp_min(sum(autodev_agent_quality_ratio_count) by (autodev_agent_id), 1)
autodev_queue_jobs{state="pending"}
autodev_worker_utilization
```

- [ ] Add Compose services with exact OSS image tags:

```yaml
otel-collector:
  image: otel/opentelemetry-collector-contrib:0.158.0
  profiles: ["observability"]

prometheus:
  image: prom/prometheus:v3.13.1
  profiles: ["observability"]

tempo:
  image: grafana/tempo:2.10.8
  profiles: ["observability"]

loki:
  image: grafana/loki:3.7.6
  profiles: ["observability"]

grafana:
  image: grafana/grafana:13.1.3
  profiles: ["observability"]
```

Use named volumes for Prometheus, Tempo, Loki, and Grafana. Add OTel environment pass-through to both backend services without making the Collector mandatory:

```yaml
OTEL_ENABLED: "${OTEL_ENABLED:-true}"
OTEL_EXPORTER_OTLP_ENDPOINT: "${OTEL_EXPORTER_OTLP_ENDPOINT:-}"
OTEL_TRACES_SAMPLER: "${OTEL_TRACES_SAMPLER:-parentbased_traceidratio}"
OTEL_TRACES_SAMPLER_ARG: "${OTEL_TRACES_SAMPLER_ARG:-1.0}"
```

- [ ] Add Make targets:

```make
observability-up:
	OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 \
	$(COMPOSE) --profile observability up --build -d \
	backend tempo loki otel-collector prometheus grafana

observability-verify:
	$(PY) scripts/verify_observability_stack.py

observability-down:
	$(COMPOSE) --profile observability down
```

Do not use `down -v`; operator data must remain recoverable.

- [ ] Implement `verify_observability_stack.py` to emit one deterministic smoke run/step/model/log through `http://localhost:4318`, force flush, and poll for at most 30 seconds for:

  - Grafana `/api/health`;
  - Prometheus query result for `autodev_run_step_duration_count`;
  - Tempo search result for service `autodev-observability-smoke`;
  - Loki query result for service `autodev-observability-smoke`.

The script exits nonzero and prints the failed backend and URL if any signal is unavailable.

- [ ] Validate static assets:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_observability_assets.py -q
docker compose -f infrastructure/docker-compose.yml --profile observability config -q
```

Expected: tests pass and Compose exits zero.

- [ ] Run the live stack check:

```bash
make observability-up
make observability-verify
make observability-down
```

Expected: verifier reports healthy Grafana plus one searchable metric, trace, and log, then exits zero.

- [ ] Commit:

```bash
git add infrastructure/observability infrastructure/docker-compose.yml scripts/verify_observability_stack.py backend/tests/unit/observability/test_observability_assets.py Makefile
git commit -m "feat(observability): provision oss telemetry stack and dashboard"
```

---

## Task 6: Prove the NFR, Publish Documentation, and Close the Story

**Files:**

- Create: `scripts/measure_observability_overhead.py`
- Create: `backend/tests/unit/observability/test_overhead_measurement.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `DESCRIPTION.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/config.md`
- Modify: `docs/ops/observability.md`
- Modify: `docs/architecture/stack_decisions.md`
- Modify: `docs/feature_matrix.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/v2_platform/phases/e11_observability_security_multitenant.md`
- Modify: `docs/v2_platform/progress.md`

**Interfaces:**

```python
@dataclass(frozen=True)
class OverheadResult:
    baseline_seconds: float
    instrumented_seconds: float
    overhead_ratio: float
    rounds: int
    iterations_per_round: int

    @property
    def within_target(self) -> bool:
        return self.overhead_ratio < 0.05

def calculate_overhead_ratio(
    baseline_seconds: float, instrumented_seconds: float
) -> float: ...

def measure_overhead(
    *, rounds: int = 7, iterations_per_round: int = 200,
    workload_seconds: float = 0.005
) -> OverheadResult: ...
```

- [ ] Add RED benchmark calculation tests:

```python
def test_overhead_ratio_is_relative_to_baseline() -> None:
    assert calculate_overhead_ratio(10.0, 10.4) == pytest.approx(0.04)


def test_overhead_result_fails_at_the_five_percent_boundary() -> None:
    result = OverheadResult(
        baseline_seconds=10.0,
        instrumented_seconds=10.5,
        overhead_ratio=0.05,
        rounds=7,
        iterations_per_round=200,
    )
    assert result.within_target is False
```

- [ ] Run RED:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability/test_overhead_measurement.py -q
```

Expected: import fails because the measurement script does not exist.

- [ ] Implement a paired median benchmark:

  - warm up both paths;
  - alternate baseline-first and instrumented-first rounds;
  - each operation performs a 5 ms representative I/O wait;
  - instrumented operations create one run span, one step span, one histogram observation, and one redacted JSON log written to a null stream;
  - use an always-on SDK provider with no exporter, matching production's nonblocking batch-export path;
  - compute the median baseline and instrumented round durations;
  - print one JSON result;
  - exit `1` when `overhead_ratio >= 0.05`.

The JSON output contract is:

```json
{
  "baseline_seconds": 7.103,
  "instrumented_seconds": 7.281,
  "overhead_ratio": 0.02506,
  "target_ratio": 0.05,
  "within_target": true,
  "rounds": 7,
  "iterations_per_round": 200,
  "workload_seconds": 0.005
}
```

The numeric measurements are runtime-generated; the schema and threshold are fixed.

- [ ] Run the benchmark:

```bash
source .venv/bin/activate && python scripts/measure_observability_overhead.py
```

Expected: exit zero and `"overhead_ratio"` strictly below `0.05`. If it fails, profile the runtime and reduce duplicate formatting/provider lookups before proceeding; do not weaken the threshold or increase the synthetic workload.

- [ ] Document every new environment variable in `.env.example` and `docs/config.md`:

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=autodev-backend
OTEL_EXPORTER_OTLP_ENDPOINT=
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0
OTEL_METRIC_EXPORT_INTERVAL_MS=5000
AUTODEV_OBSERVABILITY_TRACE_RETENTION=168h
AUTODEV_OBSERVABILITY_METRIC_RETENTION=15d
AUTODEV_OBSERVABILITY_LOG_RETENTION=168h
```

- [ ] Rewrite `docs/ops/observability.md` as the operator contract, including:

  - architecture and signal flow;
  - `make observability-up`, verify, and down commands;
  - ports and backend responsibilities;
  - span and metric naming;
  - metric-label cardinality policy;
  - trace exemplar navigation;
  - JSON log schema and redaction policy;
  - sampling modes and parent behavior;
  - retention ownership and volume behavior;
  - dashboard panel/query definitions;
  - expected failure modes;
  - emergency rollback with `OTEL_ENABLED=false`;
  - statement that full alerts, Alertmanager receivers, backup/security runbooks, and quota alerts arrive in E11-S4.

- [ ] Update project documentation:

  - `README.md` and `DESCRIPTION.md`: mark the self-hosted three-signal stack and dashboard as available.
  - `docs/architecture/stack_decisions.md`: add Collector, Tempo, Loki, Prometheus, and Grafana with ADR-017.
  - `docs/feature_matrix.md`: replace the stale “optional OTel tracing” entry with traces/metrics/logs/dashboard/sampling/retention status.
  - `docs/roadmap.md`: mark E11-S1 complete without marking E11 complete.
  - `CHANGELOG.md`: add the E11-S1 operator-facing feature and rollback flag.
  - E11 phase doc: set `Status: In progress`, `Stories: 1/4 complete`, and mark S1/T1-T3 complete.
  - `docs/v2_platform/progress.md`: set E11 to `In progress · 1/4`, set next action to E11-S2, and add a dated `2026-08-15` changelog line.

- [ ] Run graph refresh once:

```bash
source .venv/bin/activate && graphify update .
```

Expected: successful incremental graph update.

- [ ] Run the consolidated story verification:

```bash
source .venv/bin/activate && pytest backend/tests/unit/observability backend/tests/unit/jobs/test_job_observability.py backend/tests/unit/jobs/test_job_queue.py backend/tests/unit/jobs/test_queue_gaps.py backend/tests/unit/flows/test_flows_engine.py backend/tests/unit/agents/test_agent_runtime_model_gateway.py backend/tests/unit/events/test_event_catalog.py backend/tests/unit/reasoning backend/tests/unit/routing backend/tests/unit/evals backend/tests/integration/observability -q
source .venv/bin/activate && make lint-backend
source .venv/bin/activate && make typecheck-backend
source .venv/bin/activate && make test-backend
source .venv/bin/activate && make run_secret_scanning
make check-compose
source .venv/bin/activate && python scripts/measure_observability_overhead.py
```

Expected:

- all targeted and full backend tests pass;
- backend coverage remains at least 85%;
- Ruff and mypy pass;
- secret scanning passes;
- Compose configuration passes;
- benchmark reports `<5%`.

- [ ] Perform the mandatory self-review:

  - Compare every E11-S1 T1-T3 and story DoD item against the acceptance mapping.
  - Confirm each production `emit_event()` call made under an active operation receives a nonempty 32-character W3C trace ID.
  - Confirm every Flow, legacy orchestrator, and Agent Runtime step records a final status and one metric.
  - Confirm reasoning/routing callbacks still receive their exact prior `TraceEvent` payloads and order.
  - Confirm `ReasoningOutput.trace_id` remains the replay anchor.
  - Confirm no metric contains run, trace, span, step, raw path, prompt, or payload labels.
  - Confirm raw secrets are absent from captured spans, metrics, JSON logs, OTel logs, and the diff.
  - Confirm the app starts and works with no Collector and with `OTEL_ENABLED=false`.
  - Confirm dashboard queries match the metric names exposed by the live Collector.
  - Confirm no paid dependency or mandatory external service was introduced.
  - Confirm alert delivery/runbook work was not accidentally claimed as E11-S1 completion.
  - Scan for unfinished markers:

```bash
rg -n "TODO|TBD|FIXME|NotImplementedError" backend/observability infrastructure/observability scripts/verify_observability_stack.py scripts/measure_observability_overhead.py docs/ops/observability.md
```

Expected: no unfinished implementation markers.

- [ ] Commit documentation and NFR evidence:

```bash
git add scripts/measure_observability_overhead.py backend/tests/unit/observability/test_overhead_measurement.py .env.example README.md DESCRIPTION.md CHANGELOG.md docs/config.md docs/ops/observability.md docs/architecture/stack_decisions.md docs/feature_matrix.md docs/roadmap.md docs/v2_platform/phases/e11_observability_security_multitenant.md docs/v2_platform/progress.md graphify-out
git commit -m "docs(observability): publish e11-s1 operations and evidence"
```

- [ ] Merge the story into the epic branch after review:

```bash
git checkout epic/e11-observability-security-multitenant
git merge --no-ff story/e11-s1-observability
git push origin epic/e11-observability-security-multitenant
git branch -d story/e11-s1-observability
git push origin --delete story/e11-s1-observability
```

Do not open or merge the E11 epic PR yet; E11-S2 through E11-S4 remain incomplete.
