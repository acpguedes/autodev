"""Tests for the observable backup-health gauges (E11-S4)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.observability.backup_metrics import register_backup_observables
from backend.persistence.backup_status import BackupStatusStore
from backend.tests.observability_helpers import capture_observability


def _gauge_values(metrics_data: Any, name: str) -> list[float]:
    """Extract observed values for one gauge from a metrics export snapshot."""
    return [
        point.value
        for resource in metrics_data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def test_backup_gauges_report_no_data_points_before_any_backup(tmp_path: Path) -> None:
    """With no status file yet, every gauge reports zero data points."""
    status_store = BackupStatusStore(tmp_path / "backup-status.json")

    with capture_observability() as capture:
        register_backup_observables(
            meter=capture.runtime.meter_provider.get_meter("test.backup"),
            status_store=status_store,
        )
        capture.runtime.force_flush()
        metrics_data = capture.metric_reader.get_metrics_data()

    assert metrics_data is None or _gauge_values(
        metrics_data, "autodev_backup_last_attempt_timestamp_seconds"
    ) == []


def test_backup_gauges_report_recorded_status(tmp_path: Path) -> None:
    """Every documented gauge reports the durable status store's latest values."""
    status_store = BackupStatusStore(tmp_path / "backup-status.json")
    moment = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
    status_store.record(success=True, occurred_at=moment)

    with capture_observability() as capture:
        register_backup_observables(
            meter=capture.runtime.meter_provider.get_meter("test.backup"),
            status_store=status_store,
        )
        capture.runtime.force_flush()
        metrics_data = capture.metric_reader.get_metrics_data()

    assert metrics_data is not None
    assert _gauge_values(
        metrics_data, "autodev_backup_last_attempt_timestamp_seconds"
    ) == [moment.timestamp()]
    assert _gauge_values(
        metrics_data, "autodev_backup_last_success_timestamp_seconds"
    ) == [moment.timestamp()]
    assert _gauge_values(metrics_data, "autodev_backup_consecutive_failures") == [0]
    assert _gauge_values(metrics_data, "autodev_backup_last_result") == [1]


def test_backup_gauge_reports_failure_as_zero(tmp_path: Path) -> None:
    """`autodev_backup_last_result` reports zero for the most recent failure."""
    status_store = BackupStatusStore(tmp_path / "backup-status.json")
    status_store.record(success=False)

    with capture_observability() as capture:
        register_backup_observables(
            meter=capture.runtime.meter_provider.get_meter("test.backup"),
            status_store=status_store,
        )
        capture.runtime.force_flush()
        metrics_data = capture.metric_reader.get_metrics_data()

    assert metrics_data is not None
    assert _gauge_values(metrics_data, "autodev_backup_last_result") == [0]
    assert _gauge_values(
        metrics_data, "autodev_backup_last_success_timestamp_seconds"
    ) == []
    assert _gauge_values(metrics_data, "autodev_backup_consecutive_failures") == [1]
