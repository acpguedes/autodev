"""E3-S2 tests: graph execution, durable Run/Step state, events, budgets."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from backend.flows.engine import FlowEngine
from backend.flows.handlers import CallableRegistry, build_default_handlers
from backend.flows.manifest import validate_flow_manifest
from backend.flows.registry import FlowRegistry
from backend.flows.triggers import TriggerError, cron_matches, normalize_trigger
from backend.persistence.sqlite_adapter import SQLiteStore


def _linear_flow(flow_id: str = "autodev/flow-linear") -> dict[str, Any]:
    """A three-node skill pipeline with a conditional rework loop."""
    return {
        "schemaVersion": "1",
        "id": flow_id,
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "triggers": [
            {"type": "message"},
            {"type": "event", "on": "flow.run.requested"},
        ],
        "input": {
            "type": "object",
            "required": ["task"],
            "properties": {"task": {"type": "string"}},
        },
        "nodes": [
            {
                "id": "prepare",
                "type": "skill",
                "ref": "autodev/skill-prepare",
                "input": {"task": "{{ flow.input.task }}"},
            },
            {
                "id": "work",
                "type": "skill",
                "ref": "autodev/skill-work",
                "input": {"prepared": "{{ nodes.prepare.output.prepared }}"},
            },
            {"id": "gate", "type": "conditional"},
            {"id": "finish", "type": "skill", "ref": "autodev/skill-finish"},
        ],
        "edges": [
            {"from": "prepare", "to": "work"},
            {"from": "work", "to": "gate"},
            {"from": "gate", "to": "finish", "when": "{{ nodes.work.output.ok == true }}"},
            {"from": "gate", "to": "work", "when": "{{ nodes.work.output.ok == false }}"},
        ],
    }


def _engine(tmp_path: Path, **kwargs: Any) -> tuple[FlowEngine, CallableRegistry]:
    """Build an engine on a temp SQLite store with a callable registry."""
    store = SQLiteStore(f"sqlite:///{tmp_path / 'flows.db'}")
    callables = CallableRegistry()
    engine = FlowEngine(
        store=store,
        handlers=build_default_handlers(store=store, callables=callables),
        **kwargs,
    )
    return engine, callables


def _register_linear_callables(callables: CallableRegistry) -> list[str]:
    """Register the linear flow's skills, recording the execution order."""
    order: list[str] = []

    def prepare(payload: dict[str, Any]) -> dict[str, Any]:
        order.append("prepare")
        return {"prepared": f"prep:{payload['task']}"}

    def work(payload: dict[str, Any]) -> dict[str, Any]:
        order.append("work")
        return {"ok": True, "result": payload["prepared"].upper()}

    def finish(payload: dict[str, Any]) -> dict[str, Any]:
        order.append("finish")
        return {"done": True}

    callables.register("autodev/skill-prepare", prepare)
    callables.register("autodev/skill-work", work)
    callables.register("autodev/skill-finish", finish)
    return order


class TestGraphExecution:
    """A run executes the graph in the correct order (E3-S2)."""

    def test_run_executes_in_order_with_conditional_route(self, tmp_path: Path) -> None:
        """Nodes execute in graph order; the passing gate routes to finish."""
        engine, callables = _engine(tmp_path)
        order = _register_linear_callables(callables)
        engine.registry.register_raw(_linear_flow())

        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})

        assert run.status == "completed"
        assert order == ["prepare", "work", "finish"]
        assert run.output == {"done": True}

    def test_steps_persist_status_and_attempts(self, tmp_path: Path) -> None:
        """Each activation persists a step with status/attempt/sequence."""
        engine, callables = _engine(tmp_path)
        _register_linear_callables(callables)
        engine.registry.register_raw(_linear_flow())

        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})
        steps = engine.runs.list_steps(run.run_id)

        assert [step.node_id for step in steps] == ["prepare", "work", "gate", "finish"]
        assert all(step.status == "completed" for step in steps)
        assert all(step.attempt == 1 for step in steps)
        assert [step.sequence for step in steps] == [1, 2, 3, 4]
        assert steps[0].output == {"prepared": "prep:ship"}

    def test_state_is_durable_across_engine_instances(self, tmp_path: Path) -> None:
        """A second engine on the same store sees the same run state."""
        engine, callables = _engine(tmp_path)
        _register_linear_callables(callables)
        engine.registry.register_raw(_linear_flow())
        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})

        store = SQLiteStore(f"sqlite:///{tmp_path / 'flows.db'}")
        second = FlowEngine(store=store)
        reloaded = second.runs.get_run(run.run_id)

        assert reloaded is not None
        assert reloaded.status == "completed"
        assert reloaded.state["nodes"]["finish"]["output"] == {"done": True}

    def test_failed_node_fails_run_closed(self, tmp_path: Path) -> None:
        """A node exception fails the step and the run, with events."""
        engine, callables = _engine(tmp_path)
        _register_linear_callables(callables)

        def boom(payload: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("kaput")

        callables.register("autodev/skill-work", boom)
        engine.registry.register_raw(_linear_flow())

        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})

        assert run.status == "failed"
        assert run.stop_reason == "node_failed"
        steps = engine.runs.list_steps(run.run_id)
        assert steps[-1].status == "failed"
        assert "kaput" in steps[-1].error
        names = [event.name for event in engine.runs.list_events(run.run_id)]
        assert names[-1] == "flow.run.failed"
        assert "run.step.failed" in names

    def test_unsupported_node_type_fails_closed(self, tmp_path: Path) -> None:
        """Node types without a handler (subflow/map until S5) fail the run."""
        engine, callables = _engine(tmp_path)
        _register_linear_callables(callables)
        raw = _linear_flow()
        raw["nodes"].append(
            {
                "id": "review",
                "type": "subflow",
                "ref": "autodev/sub-review",
            }
        )
        raw["edges"].append({"from": "finish", "to": "review"})
        engine.registry.register_raw(raw)

        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})

        assert run.status == "failed"
        assert run.stop_reason == "unsupported_node"

    def test_missing_required_input_rejected(self, tmp_path: Path) -> None:
        """Run input must satisfy the flow's declared required fields."""
        engine, callables = _engine(tmp_path)
        _register_linear_callables(callables)
        engine.registry.register_raw(_linear_flow())

        from backend.flows.engine import FlowRunError

        with pytest.raises(FlowRunError, match="missing required input"):
            engine.start_run("autodev/flow-linear", input={})


class TestEvents:
    """flow.run.started / run.step.completed events are emitted (E3-S2 DoD)."""

    def test_lifecycle_events_emitted_in_order(self, tmp_path: Path) -> None:
        """The durable event store records the full ordered lifecycle."""
        engine, callables = _engine(tmp_path)
        _register_linear_callables(callables)
        engine.registry.register_raw(_linear_flow())

        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})
        events = engine.runs.list_events(run.run_id)

        names = [event.name for event in events]
        assert names[0] == "flow.run.started"
        assert names[-1] == "flow.run.completed"
        assert names.count("run.step.started") == 4
        assert names.count("run.step.completed") == 4
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        started = events[0]
        assert started.payload["flowId"] == "autodev/flow-linear"
        assert started.payload["entryNodeId"] == "prepare"
        completed = [event for event in events if event.name == "run.step.completed"]
        assert completed[0].payload["nodeId"] == "prepare"
        assert completed[0].payload["nextNodeId"] == "work"


class TestBudgets:
    """Run budgets fail closed (reference doc Principle 2.5)."""

    def test_cost_budget_fails_closed(self, tmp_path: Path) -> None:
        """Accumulated node cost beyond maxCostUsd stops the run."""
        engine, callables = _engine(tmp_path)
        raw = _linear_flow()
        raw["budgets"] = {"maxCostUsd": 0.5, "maxWallClockSec": 60, "maxTokens": 1000}
        engine.registry.register_raw(raw)

        from backend.flows.handlers import NodeContext, NodeOutcome

        def costly_handler(ctx: NodeContext) -> NodeOutcome:
            return NodeOutcome(
                output={"ok": True, "prepared": "x"}, metrics={"cost_usd": 0.4}
            )

        engine.handlers.register("skill", costly_handler)
        engine.handlers.register("conditional", costly_handler)

        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})

        assert run.status == "failed"
        assert run.stop_reason == "budget_exhausted"
        names = [event.name for event in engine.runs.list_events(run.run_id)]
        assert names[-1] == "flow.run.failed"

    def test_engine_step_cap_fails_closed(self, tmp_path: Path) -> None:
        """A guarded loop that never exits hits the engine step cap."""
        engine, callables = _engine(tmp_path, max_steps_per_run=10)
        raw = _linear_flow()
        engine.registry.register_raw(raw)

        def never_ok(payload: dict[str, Any]) -> dict[str, Any]:
            return {"ok": False, "prepared": "x"}

        callables.register("autodev/skill-prepare", lambda p: {"prepared": "x"})
        callables.register("autodev/skill-work", never_ok)

        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})

        assert run.status == "failed"
        assert run.stop_reason == "budget_exhausted"


class TestTriggers:
    """Triggers start runs and undeclared triggers fail closed (E3-S2-T3)."""

    def test_trigger_starts_run_and_is_persisted(self, tmp_path: Path) -> None:
        """A declared message trigger starts a run recording its origin."""
        engine, callables = _engine(tmp_path)
        _register_linear_callables(callables)
        manifest = engine.registry.register_raw(_linear_flow())

        trigger = normalize_trigger(manifest, "message", payload={"channel": "chat"})
        run = engine.start_run(
            manifest.id, input={"task": "ship"}, trigger=trigger.to_document()
        )

        assert run.status == "completed"
        stored = engine.runs.get_run(run.run_id)
        assert stored is not None
        assert stored.trigger == {"type": "message", "payload": {"channel": "chat"}}

    def test_undeclared_trigger_rejected(self, tmp_path: Path) -> None:
        """Trigger types the manifest does not declare fail closed."""
        engine, _ = _engine(tmp_path)
        manifest = engine.registry.register_raw(_linear_flow())
        with pytest.raises(TriggerError, match="does not declare"):
            normalize_trigger(manifest, "webhook")
        with pytest.raises(TriggerError, match="does not subscribe"):
            normalize_trigger(manifest, "event", event="other.event.happened")

    def test_cron_matching(self) -> None:
        """The 5-field cron matcher covers *, steps, ranges, and lists."""
        from datetime import datetime

        at = datetime(2026, 7, 6, 14, 30)  # Monday
        assert cron_matches("* * * * *", at)
        assert cron_matches("*/15 * * * *", at)
        assert cron_matches("30 14 * * 1", at)
        assert cron_matches("0-45 9-17 * 7 1-5", at)
        assert not cron_matches("31 * * * *", at)
        assert not cron_matches("* * * * 0", at)
        with pytest.raises(TriggerError):
            cron_matches("bad cron", at)


class TestConcurrency:
    """>= 100 concurrent runs on one engine (E3-S2 NFR, scaled to CI)."""

    def test_100_concurrent_runs_complete_consistently(self, tmp_path: Path) -> None:
        """100 runs executed across 25 threads all complete with full state."""
        engine, callables = _engine(tmp_path)
        _register_linear_callables(callables)
        engine.registry.register_raw(_linear_flow())

        def start(index: int) -> str:
            run = engine.start_run(
                "autodev/flow-linear", input={"task": f"task-{index}"}
            )
            return run.run_id

        with ThreadPoolExecutor(max_workers=25) as pool:
            run_ids = list(pool.map(start, range(100)))

        assert len(set(run_ids)) == 100
        for run_id in run_ids:
            run = engine.runs.get_run(run_id)
            assert run is not None and run.status == "completed"
            steps = engine.runs.list_steps(run_id)
            assert [step.node_id for step in steps] == [
                "prepare",
                "work",
                "gate",
                "finish",
            ]
            events = engine.runs.list_events(run_id)
            assert events[0].name == "flow.run.started"
            assert events[-1].name == "flow.run.completed"


class TestFlowRegistry:
    """Versioned flow registration and resolution."""

    def test_register_and_resolve_versions(self, tmp_path: Path) -> None:
        """The registry resolves SemVer ranges to the highest match."""
        store = SQLiteStore(f"sqlite:///{tmp_path / 'registry.db'}")
        registry = FlowRegistry(store)
        v1 = _linear_flow()
        v2 = _linear_flow()
        v2["version"] = "1.5.0"
        v3 = _linear_flow()
        v3["version"] = "2.0.0"
        for raw in (v1, v2, v3):
            result = validate_flow_manifest(raw)
            assert result.manifest is not None
            registry.register(result.manifest)

        assert registry.resolve("autodev/flow-linear").version == "2.0.0"
        assert registry.resolve("autodev/flow-linear", ">=1.0 <2.0").version == "1.5.0"
        with pytest.raises(KeyError):
            registry.resolve("autodev/flow-linear", ">=3.0")
        catalog = registry.catalog()
        assert catalog["schemaVersion"] == "1"
        assert len(catalog["flows"]) == 3
