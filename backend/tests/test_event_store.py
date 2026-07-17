"""Tests for the durable Event Store (E8-S2).

Covers the four story subtasks: append-only per-partition ordering (T1),
run reconstruction from stored events plus deterministic replay (T2),
transactional projections for fast status queries (T3), and retention-based
compaction (T4) — including the bus wiring that persists every published
envelope when ``autodev_event_store_enabled`` is on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.config.settings import reset_settings_cache
from backend.events.catalog import make_envelope
from backend.events.runtime import (
    emit_event,
    get_event_bus,
    get_event_store,
    reset_event_bus_for_tests,
    reset_event_store_for_tests,
)
from backend.events.store import EventStore
from backend.flows.engine import FlowEngine
from backend.flows.handlers import CallableRegistry, build_default_handlers
from backend.persistence.database import reset_store_cache
from backend.persistence.sqlite_adapter import SQLiteStore


@pytest.fixture()
def store(tmp_path: Path) -> EventStore:
    """Build an :class:`EventStore` on a throwaway SQLite database.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        A fresh Event Store instance.
    """
    return EventStore(SQLiteStore(f"sqlite:///{tmp_path / 'events.db'}"))


def _envelope(
    run_id: str,
    type_: str,
    data: dict[str, object],
    tenant_id: str = "default",
):
    """Build a schema-valid envelope for a run partition.

    Args:
        run_id: Partition key.
        type_: Catalog event type.
        data: Payload for the type's data model.
        tenant_id: Tenant for the envelope.

    Returns:
        The validated envelope.
    """
    return make_envelope(
        type_, tenant_id=tenant_id, partition_key=run_id, data=data
    )


def _lifecycle(store: EventStore, run_id: str, *, fail: bool = False) -> None:
    """Append a full run lifecycle to a partition.

    Args:
        store: Event Store under test.
        run_id: Partition key of the synthetic run.
        fail: Whether the run ends in ``flow.run.failed``.
    """
    store.append(
        _envelope(run_id, "flow.run.started", {"flowId": "f", "flowVersion": "1.0.0"})
    )
    store.append(_envelope(run_id, "run.step.started", {"stepKey": "s1", "agent": "a"}))
    if fail:
        store.append(
            _envelope(
                run_id, "run.step.failed", {"stepKey": "s1", "error": "boom", "attempt": 1}
            )
        )
        store.append(
            _envelope(run_id, "flow.run.failed", {"error": "boom", "failedStep": "s1"})
        )
    else:
        store.append(
            _envelope(
                run_id,
                "run.step.completed",
                {"stepKey": "s1", "status": "completed", "attempt": 1},
            )
        )
        store.append(
            _envelope(
                run_id,
                "flow.run.completed",
                {"status": "completed", "costUsd": 0.5, "tokens": 42},
            )
        )


class TestAppendOrdering:
    """E8-S2-T1 — append-only log ordered per partition."""

    def test_sequences_are_monotonic_per_partition(self, store: EventStore) -> None:
        """Each partition gets its own 1-based, gap-free sequence."""
        _lifecycle(store, "run-a")
        store.append(
            _envelope("run-b", "flow.run.started", {"flowId": "f", "flowVersion": "1.0.0"})
        )

        events_a = store.list_events("run-a")
        events_b = store.list_events("run-b")
        assert [event.sequence for event in events_a] == [1, 2, 3, 4]
        assert [event.sequence for event in events_b] == [1]
        assert [event.envelope.type for event in events_a] == [
            "flow.run.started",
            "run.step.started",
            "run.step.completed",
            "flow.run.completed",
        ]

    def test_list_events_supports_exclusive_resume(self, store: EventStore) -> None:
        """``after_sequence`` skips already-consumed events."""
        _lifecycle(store, "run-a")

        tail = store.list_events("run-a", after_sequence=2)
        assert [event.sequence for event in tail] == [3, 4]

    def test_envelope_round_trips_losslessly(self, store: EventStore) -> None:
        """The stored row decodes back to the published envelope."""
        published = _envelope(
            "run-a", "flow.run.started", {"flowId": "f", "flowVersion": "1.0.0"}
        )
        store.append(published)

        decoded = store.list_events("run-a")[0].envelope
        assert decoded == published


class TestProjections:
    """E8-S2-T3 — materialized per-partition status summaries."""

    def test_projection_tracks_status_and_counts(self, store: EventStore) -> None:
        """The projection follows the lifecycle to its terminal status."""
        _lifecycle(store, "run-a")

        projection = store.get_projection("run-a")
        assert projection is not None
        assert projection.status == "completed"
        assert projection.last_sequence == 4
        assert projection.last_event_type == "flow.run.completed"
        assert projection.counts == {
            "flow.run.started": 1,
            "run.step.started": 1,
            "run.step.completed": 1,
            "flow.run.completed": 1,
        }

    def test_projection_reports_failed_runs(self, store: EventStore) -> None:
        """A failing lifecycle lands the projection in ``failed``."""
        _lifecycle(store, "run-a", fail=True)

        projection = store.get_projection("run-a")
        assert projection is not None
        assert projection.status == "failed"

    def test_list_projections_filters(self, store: EventStore) -> None:
        """Tenant and status filters narrow the projection listing."""
        _lifecycle(store, "run-a")
        _lifecycle(store, "run-b", fail=True)

        failed = store.list_projections(status="failed")
        assert [projection.partition_key for projection in failed] == ["run-b"]
        assert store.get_projection("missing") is None


class TestReconstruction:
    """E8-S2-T2 — a run is reconstructible purely from stored events."""

    def test_reconstructs_synthetic_lifecycle(self, store: EventStore) -> None:
        """Reconstruction folds events into status, steps, and totals."""
        _lifecycle(store, "run-a")

        view = store.reconstruct_run("run-a")
        assert view["status"] == "completed"
        assert view["eventCount"] == 4
        assert view["costUsd"] == 0.5
        assert view["tokens"] == 42
        assert view["steps"] == [
            {
                "stepKey": "s1",
                "agent": "a",
                "status": "completed",
                "attempt": 1,
                "sequence": 2,
            }
        ]

    def test_reconstruction_matches_engine_run_and_replay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DoD: a real run is reconstructed from the event store and its
        deterministic replay reproduces the recorded decision path."""
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'run.db'}")
        monkeypatch.delenv("AUTODEV_EVENT_BUS", raising=False)
        monkeypatch.delenv("AUTODEV_EVENT_STORE_ENABLED", raising=False)
        reset_settings_cache()
        reset_store_cache()
        reset_event_bus_for_tests()
        reset_event_store_for_tests()
        try:
            callables = CallableRegistry()
            callables.register("autodev/skill-echo", lambda payload: {"echo": payload})
            engine = FlowEngine(handlers=build_default_handlers(callables=callables))
            engine.registry.register_raw(
                {
                    "schemaVersion": "1",
                    "id": "autodev/flow-events",
                    "version": "1.0.0",
                    "hostApi": ">=2.0 <3.0",
                    "nodes": [
                        {"id": "only", "type": "skill", "ref": "autodev/skill-echo"}
                    ],
                    "edges": [],
                }
            )

            run = engine.start_run("autodev/flow-events", input={"x": 1})
            assert run.status == "completed"

            view = get_event_store().reconstruct_run(run.run_id)
            assert view["status"] == run.status
            recorded_steps = engine.runs.list_steps(run.run_id)
            assert [step["stepKey"] for step in view["steps"]] == [
                step.node_id for step in recorded_steps if step.status == "completed"
            ]
            assert all(step["status"] == "completed" for step in view["steps"])

            report = engine.replay_run(run.run_id)
            assert report.deterministic, report.divergences
        finally:
            reset_settings_cache()
            reset_store_cache()
            reset_event_bus_for_tests()
            reset_event_store_for_tests()


class TestBusWiring:
    """The bus singleton persists envelopes when the Event Store is enabled."""

    def test_emit_event_persists_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``emit_event`` through the process bus lands in the State Store."""
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'wired.db'}")
        monkeypatch.delenv("AUTODEV_EVENT_BUS", raising=False)
        monkeypatch.delenv("AUTODEV_EVENT_STORE_ENABLED", raising=False)
        reset_settings_cache()
        reset_store_cache()
        reset_event_bus_for_tests()
        reset_event_store_for_tests()
        try:
            emit_event(
                "flow.run.started",
                tenant_id="tenant-1",
                partition_key="run-w",
                data={"flowId": "f", "flowVersion": "1.0.0"},
            )
            stored = get_event_store().list_events("run-w")
            assert [event.envelope.type for event in stored] == ["flow.run.started"]
            assert stored[0].envelope.tenantId == "tenant-1"
        finally:
            reset_settings_cache()
            reset_store_cache()
            reset_event_bus_for_tests()
            reset_event_store_for_tests()

    def test_disabled_store_keeps_bus_ephemeral(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the flag off, publishing writes nothing durable."""
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'off.db'}")
        monkeypatch.setenv("AUTODEV_EVENT_STORE_ENABLED", "false")
        monkeypatch.delenv("AUTODEV_EVENT_BUS", raising=False)
        reset_settings_cache()
        reset_store_cache()
        reset_event_bus_for_tests()
        reset_event_store_for_tests()
        try:
            emit_event(
                "flow.run.started",
                tenant_id="default",
                partition_key="run-off",
                data={"flowId": "f", "flowVersion": "1.0.0"},
            )
            assert get_event_bus().replay("run-off")  # delivered on the bus
            assert get_event_store().list_events("run-off") == []
        finally:
            reset_settings_cache()
            reset_store_cache()
            reset_event_bus_for_tests()
            reset_event_store_for_tests()


class TestRetention:
    """E8-S2-T4 — retention-based compaction of terminal partitions."""

    def test_purges_only_terminal_partitions(self, store: EventStore) -> None:
        """Old events of terminal runs go; active runs keep their log."""
        _lifecycle(store, "run-done")
        store.append(
            _envelope(
                "run-live", "flow.run.started", {"flowId": "f", "flowVersion": "1.0.0"}
            )
        )

        future = datetime.now(timezone.utc) + timedelta(days=10)
        deleted = store.purge_expired(retention_days=5, now=future)

        assert deleted == 4
        assert store.list_events("run-done") == []
        assert len(store.list_events("run-live")) == 1
        # The projection survives compaction as the durable summary.
        projection = store.get_projection("run-done")
        assert projection is not None
        assert projection.status == "completed"
        assert projection.counts["flow.run.completed"] == 1

    def test_recent_events_survive_the_window(self, store: EventStore) -> None:
        """Events newer than the retention window are kept."""
        _lifecycle(store, "run-done")

        deleted = store.purge_expired(retention_days=5)

        assert deleted == 0
        assert len(store.list_events("run-done")) == 4

    def test_negative_retention_disables_purging(self, store: EventStore) -> None:
        """``retention_days < 0`` means keep everything forever."""
        _lifecycle(store, "run-done")

        future = datetime.now(timezone.utc) + timedelta(days=365)
        assert store.purge_expired(retention_days=-1, now=future) == 0
        assert len(store.list_events("run-done")) == 4
