"""Contracts for the self-hosted E11-S1 observability stack assets."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
OBSERVABILITY = ROOT / "infrastructure" / "observability"
COLLECTOR = OBSERVABILITY / "otel-collector.yaml"
PROMETHEUS = OBSERVABILITY / "prometheus.yaml"
PROMETHEUS_RULES = OBSERVABILITY / "prometheus-rules.yml"
TEMPO = OBSERVABILITY / "tempo.yaml"
LOKI = OBSERVABILITY / "loki.yaml"
DATASOURCES = (
    OBSERVABILITY
    / "grafana"
    / "provisioning"
    / "datasources"
    / "datasources.yaml"
)
DASHBOARD_PROVISIONING = (
    OBSERVABILITY
    / "grafana"
    / "provisioning"
    / "dashboards"
    / "dashboards.yaml"
)
DASHBOARD = OBSERVABILITY / "grafana" / "dashboards" / "autodev-overview.json"
COMPOSE = ROOT / "infrastructure" / "docker-compose.yml"
VERIFIER = ROOT / "scripts" / "verify_observability_stack.py"


def _yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping from a repository asset.

    Args:
        path: YAML file to load.

    Returns:
        Parsed top-level mapping.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_verifier() -> ModuleType:
    """Import the smoke verifier from its repository script path.

    Returns:
        Imported verifier module.
    """
    if not VERIFIER.exists():
        pytest.fail(f"missing verifier: {VERIFIER}")
    spec = importlib.util.spec_from_file_location("observability_verifier", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_collector_routes_all_three_signals() -> None:
    """Collector pipelines route traces, metrics, and logs to OSS backends."""
    config = _yaml(COLLECTOR)
    pipelines = config["service"]["pipelines"]

    assert config["receivers"]["otlp"]["protocols"]["http"]["endpoint"] == (
        "0.0.0.0:4318"
    )
    assert pipelines["traces"]["exporters"] == ["otlphttp/tempo"]
    assert pipelines["metrics"]["exporters"] == ["prometheus"]
    assert pipelines["logs"]["exporters"] == ["otlphttp/loki"]
    assert config["exporters"]["prometheus"] == {
        "endpoint": "0.0.0.0:9464",
        "enable_open_metrics": True,
        "translation_strategy": "UnderscoreEscapingWithoutSuffixes",
    }
    assert "without_units" not in config["exporters"]["prometheus"]


def test_retention_and_local_storage_are_operator_configurable() -> None:
    """Every signal backend uses persistent local storage and bounded retention."""
    tempo_text = TEMPO.read_text(encoding="utf-8")
    loki_text = LOKI.read_text(encoding="utf-8")
    compose = _yaml(COMPOSE)

    assert "${AUTODEV_OBSERVABILITY_TRACE_RETENTION}" in tempo_text
    assert "${AUTODEV_OBSERVABILITY_LOG_RETENTION}" in loki_text
    assert _yaml(TEMPO)["storage"]["trace"]["backend"] == "local"
    assert _yaml(LOKI)["compactor"]["retention_enabled"] is True
    prometheus_command = " ".join(compose["services"]["prometheus"]["command"])
    assert "${AUTODEV_OBSERVABILITY_METRIC_RETENTION:-15d}" in prometheus_command
    for volume in (
        "autodev_prometheus",
        "autodev_tempo",
        "autodev_loki",
        "autodev_grafana",
    ):
        assert volume in compose["volumes"]


def test_prometheus_scrapes_collector_and_loads_recording_rules() -> None:
    """Prometheus consumes normalized Collector metrics and recording rules."""
    config = _yaml(PROMETHEUS)
    rules = _yaml(PROMETHEUS_RULES)

    assert config["rule_files"] == ["/etc/prometheus/prometheus-rules.yml"]
    assert config["scrape_configs"] == [
        {
            "job_name": "otel-collector",
            "honor_labels": True,
            "static_configs": [{"targets": ["otel-collector:9464"]}],
        }
    ]
    records = {rule["record"]: rule["expr"] for rule in rules["groups"][0]["rules"]}
    assert set(records) == {
        "autodev:http_error_ratio:rate5m",
        "autodev:http_latency_p95_seconds:rate5m",
    }
    assert "http_response_status_code" in records[
        "autodev:http_error_ratio:rate5m"
    ]
    assert "http_route" in records["autodev:http_latency_p95_seconds:rate5m"]


def test_grafana_provisions_three_correlated_datasources() -> None:
    """Grafana links metrics, traces, and logs using stable data-source UIDs."""
    config = _yaml(DATASOURCES)
    datasources = {item["uid"]: item for item in config["datasources"]}

    assert set(datasources) == {"prometheus", "tempo", "loki"}
    assert datasources["tempo"]["jsonData"]["serviceMap"]["datasourceUid"] == (
        "prometheus"
    )
    assert datasources["tempo"]["jsonData"]["tracesToLogsV2"]["datasourceUid"] == (
        "loki"
    )
    derived_field = datasources["loki"]["jsonData"]["derivedFields"][0]
    assert derived_field["matcherRegex"] == '"trace_id":"([0-9a-f]{32})"'
    assert derived_field["datasourceUid"] == "tempo"
    exemplar = datasources["prometheus"]["jsonData"][
        "exemplarTraceIdDestinations"
    ][0]
    assert exemplar == {"datasourceUid": "tempo", "name": "trace_id"}

    provisioning = _yaml(DASHBOARD_PROVISIONING)
    assert provisioning["providers"][0]["options"]["path"] == (
        "/var/lib/grafana/dashboards"
    )


def test_dashboard_contains_required_operational_panels_and_normalized_queries() -> None:
    """The dashboard covers RED/USE/cost/quality with Task 1 label names."""
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    required_titles = {
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
    }

    assert set(panels) == required_titles
    queries = "\n".join(
        target["expr"]
        for panel in panels.values()
        for target in panel.get("targets", [])
    )
    for metric in (
        "http_server_request_duration_count",
        "autodev_run_step_duration_bucket",
        "gen_ai_client_operation_duration_bucket",
        "autodev_model_cost_usd_total",
        "autodev_model_tokens_total",
        "autodev_agent_quality_ratio_sum",
        "autodev_queue_jobs",
        "autodev_worker_utilization",
    ):
        assert metric in queries
    assert "autodev_agent" in queries
    assert "autodev_tenant" in queries
    assert "gen_ai_token_type" in queries
    assert "autodev_agent_id" not in queries
    assert "autodev_tenant_id" not in queries


def test_compose_profile_uses_exact_pins_ports_security_and_persistence() -> None:
    """The optional profile is pinned, bounded, persistent, and host-accessible."""
    compose = _yaml(COMPOSE)
    services = compose["services"]
    expected = {
        "otel-collector": "otel/opentelemetry-collector-contrib:0.158.0",
        "prometheus": "prom/prometheus:v3.13.1",
        "tempo": "grafana/tempo:2.10.8",
        "loki": "grafana/loki:3.7.6",
        "grafana": "grafana/grafana:13.1.3",
    }
    expected_ports = {
        "otel-collector": "4318:4318",
        "prometheus": "9090:9090",
        "tempo": "3200:3200",
        "loki": "3100:3100",
        "grafana": "3001:3000",
    }

    for name, image in expected.items():
        service = services[name]
        assert service["image"] == image
        assert service["profiles"] == ["observability"]
        assert expected_ports[name] in service["ports"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["pids_limit"] > 0
    assert "-config.expand-env=true" in services["tempo"]["command"]
    assert "-config.expand-env=true" in services["loki"]["command"]
    assert "--enable-feature=exemplar-storage" in services["prometheus"]["command"]

    for backend in ("backend", "backend-prod"):
        environment = services[backend]["environment"]
        assert environment["OTEL_ENABLED"] == "${OTEL_ENABLED:-true}"
        assert environment["OTEL_EXPORTER_OTLP_ENDPOINT"] == (
            "${OTEL_EXPORTER_OTLP_ENDPOINT:-}"
        )
        assert environment["OTEL_TRACES_SAMPLER"] == (
            "${OTEL_TRACES_SAMPLER:-parentbased_traceidratio}"
        )
        assert environment["OTEL_TRACES_SAMPLER_ARG"] == (
            "${OTEL_TRACES_SAMPLER_ARG:-1.0}"
        )


def test_make_targets_start_verify_and_preserve_observability_data() -> None:
    """Make exposes the profile lifecycle without deleting named volumes."""
    completed = subprocess.run(
        ["make", "-n", "observability-up", "observability-verify", "observability-down"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--profile observability up --build -d" in completed.stdout
    assert "scripts/verify_observability_stack.py" in completed.stdout
    assert "--profile observability down" in completed.stdout
    assert "down -v" not in completed.stdout


def test_verifier_has_one_deadline_and_actionable_backend_failures() -> None:
    """The smoke verifier bounds all polling and identifies failed backends."""
    verifier = _load_verifier()
    checks = verifier.build_backend_checks()

    assert verifier.POLL_TIMEOUT_SECONDS == 30.0
    assert {check.name: check.url for check in checks} == {
        "Grafana": "http://localhost:3001/api/health",
        "Prometheus": (
            "http://localhost:9090/api/v1/query?"
            "query=autodev_run_step_duration_count%7Bjob%3D%22"
            "autodev-observability-smoke%22%7D"
        ),
        "Tempo": (
            "http://localhost:3200/api/search?"
            "q=%7Bresource.service.name%3D%22autodev-observability-smoke%22%7D"
        ),
        "Loki": (
            "http://localhost:3100/loki/api/v1/query_range?"
            "query=%7Bservice_name%3D%22autodev-observability-smoke%22%7D&limit=1"
        ),
    }

    def unavailable(_: str, __: float) -> dict[str, Any]:
        """Return a valid response that has no searchable result."""
        return {"status": "success", "data": {"result": []}}

    with pytest.raises(verifier.VerificationError) as error:
        verifier.wait_for_backends(
            checks,
            timeout_seconds=0.0,
            request_json=unavailable,
            sleep=lambda _: None,
        )
    message = str(error.value)
    for check in checks:
        assert check.name in message
        assert check.url in message


def test_prometheus_readiness_rejects_unrelated_persisted_series() -> None:
    """A stale metric from another service cannot satisfy the smoke contract."""
    verifier = _load_verifier()
    prometheus = next(
        check for check in verifier.build_backend_checks() if check.name == "Prometheus"
    )

    unrelated = {
        "status": "success",
        "data": {
            "result": [
                {
                    "metric": {
                        "__name__": "autodev_run_step_duration_count",
                        "job": "unrelated-service",
                    },
                    "value": [1, "1"],
                }
            ]
        },
    }
    smoke = {
        "status": "success",
        "data": {
            "result": [
                {
                    "metric": {
                        "__name__": "autodev_run_step_duration_count",
                        "job": verifier.SMOKE_SERVICE_NAME,
                    },
                    "value": [1, "1"],
                }
            ]
        },
    }

    assert prometheus.ready(unrelated) is False
    assert prometheus.ready(smoke) is True


def test_verifier_bootstraps_repo_imports_for_direct_script_execution() -> None:
    """The Make entrypoint can load backend modules without package installation."""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import runpy; "
                f"runpy.run_path({str(VERIFIER)!r}, run_name='verifier_import')"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
