"""Contracts for the E11-S4 backup alert rules and Alertmanager assets."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
OBSERVABILITY = ROOT / "infrastructure" / "observability"
PROMETHEUS = OBSERVABILITY / "prometheus.yaml"
_RULES = OBSERVABILITY / "prometheus-rules.yml"
ALERTMANAGER = OBSERVABILITY / "alertmanager.yml"
COMPOSE = ROOT / "infrastructure" / "docker-compose.yml"


def test_prometheus_targets_alertmanager() -> None:
    """Prometheus is wired to deliver firing alerts to the local Alertmanager."""
    config = yaml.safe_load(PROMETHEUS.read_text(encoding="utf-8"))
    targets = config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]
    assert "alertmanager:9093" in targets


def test_backup_alerts_are_actionable() -> None:
    """Every backup alert is scoped, owned, documented, and links a runbook."""
    rules = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    alerts = {
        rule["alert"]: rule
        for group in rules["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }

    backup_alert_names = {
        "AutoDevBackupNeverSucceeded",
        "AutoDevBackupStale",
        "AutoDevBackupFailing",
    }
    assert backup_alert_names <= alerts.keys()

    for name in backup_alert_names:
        alert = alerts[name]
        assert alert["labels"]["severity"] in {"warning", "critical"}
        assert alert["labels"]["service"] == "backup"
        assert alert["annotations"]["summary"]
        assert alert["annotations"]["description"]
        assert alert["annotations"]["runbook_url"].startswith("https://")

    assert "> 300" in alerts["AutoDevBackupStale"]["expr"]
    assert "> 0" in alerts["AutoDevBackupFailing"]["expr"]


def test_postgres_pool_alerts_are_actionable() -> None:
    """Every E60-S4 PostgreSQL pooling alert is scoped, owned, documented, and links a runbook."""
    rules = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    alerts = {
        rule["alert"]: rule
        for group in rules["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }

    postgres_pool_alert_names = {
        "AutoDevPostgresPoolSaturated",
        "AutoDevPostgresDeadlockRateRising",
    }
    assert postgres_pool_alert_names <= alerts.keys()

    for name in postgres_pool_alert_names:
        alert = alerts[name]
        assert alert["labels"]["severity"] in {"warning", "critical"}
        assert alert["labels"]["service"] == "postgres-pool"
        assert alert["annotations"]["summary"]
        assert alert["annotations"]["description"]
        assert alert["annotations"]["runbook_url"].startswith("https://")


def test_backup_stale_alert_fires_after_a_single_missed_five_minute_rpo() -> None:
    """The stale-backup threshold is exactly the five-minute RPO window."""
    rules = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    alerts = {
        rule["alert"]: rule
        for group in rules["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }
    assert "300" in alerts["AutoDevBackupStale"]["expr"]


def test_backup_failing_alert_fires_on_a_single_consecutive_failure() -> None:
    """One consecutive failure is already alertable, not batched behind a threshold."""
    rules = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    alerts = {
        rule["alert"]: rule
        for group in rules["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }
    assert alerts["AutoDevBackupFailing"]["expr"].strip() == (
        "autodev_backup_consecutive_failures > 0"
    )


def test_alertmanager_has_a_default_route_and_receiver() -> None:
    """Alertmanager has a default route pointing at a defined receiver."""
    config = yaml.safe_load(ALERTMANAGER.read_text(encoding="utf-8"))
    receiver_names = {receiver["name"] for receiver in config["receivers"]}
    assert config["route"]["receiver"] in receiver_names


def test_compose_places_alertmanager_under_the_observability_profile() -> None:
    """Alertmanager is gated behind the existing `observability` Compose profile."""
    config = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    alertmanager = config["services"]["alertmanager"]
    assert alertmanager["profiles"] == ["observability"]
    assert "9093:9093" in alertmanager["ports"]
