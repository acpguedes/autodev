"""Observable backup-health gauges, registered through the E11-S1 meter.

No parallel metrics registry: these gauges are read on demand from the
durable :class:`~backend.persistence.backup_status.BackupStatusStore` and
exported through the same OpenTelemetry meter every other AutoDev metric
uses.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from opentelemetry.metrics import CallbackOptions, Meter, Observation

from backend.persistence.backup_status import BackupStatusStore


def register_backup_observables(
    *,
    meter: Meter,
    status_store: BackupStatusStore,
) -> None:
    """Register observable backup-health gauges.

    Args:
        meter: Meter supplied by E11-S1.
        status_store: Durable source of sanitized backup state.
    """

    def value(field: str) -> Callable[[CallbackOptions], Iterable[Observation]]:
        """Build a callback observing one sanitized status field.

        Args:
            field: Attribute name on :class:`~backend.persistence.backup_status.BackupStatus`.

        Returns:
            A zero-or-one-observation callback for the given field.
        """

        def observe(_: CallbackOptions) -> Iterable[Observation]:
            status = status_store.read()
            if status is None:
                return ()
            observed = getattr(status, field)
            if observed is None:
                return ()
            if field == "last_result":
                observed = 1 if observed == "success" else 0
            return (Observation(float(observed)),)

        return observe

    meter.create_observable_gauge(
        "autodev_backup_last_attempt_timestamp_seconds",
        callbacks=[value("last_attempt_timestamp")],
        description="Unix timestamp of the latest backup attempt",
        unit="s",
    )
    meter.create_observable_gauge(
        "autodev_backup_last_success_timestamp_seconds",
        callbacks=[value("last_success_timestamp")],
        description="Unix timestamp of the latest successful backup",
        unit="s",
    )
    meter.create_observable_gauge(
        "autodev_backup_consecutive_failures",
        callbacks=[value("consecutive_failures")],
        description="Number of consecutive failed backup attempts",
    )
    meter.create_observable_gauge(
        "autodev_backup_last_result",
        callbacks=[value("last_result")],
        description="Latest backup result, one for success and zero for failure",
    )
    meter.create_observable_gauge(
        "autodev_backup_last_duration_seconds",
        callbacks=[value("last_duration_seconds")],
        description=(
            "Wall-clock duration of the latest backup attempt -- monitor "
            "against the backup schedule interval for the RPO worst-case "
            "window (E59-S3-T2)"
        ),
        unit="s",
    )


__all__ = ["register_backup_observables"]
