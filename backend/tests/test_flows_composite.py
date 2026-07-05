"""E3-S5 tests: composite nodes (sub-flow, map/reduce, budget propagation)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from backend.flows.composite import MAX_COMPOSITE_DEPTH
from backend.flows.engine import FlowEngine
from backend.flows.handlers import (
    CallableRegistry,
    NodeContext,
    NodeOutcome,
    build_default_handlers,
)
from backend.persistence.sqlite_adapter import SQLiteStore


def _engine(tmp_path: Path, **kwargs: Any) -> tuple[FlowEngine, CallableRegistry]:
    """Build an engine on a temp SQLite store with a callable registry.

    Args:
        tmp_path: Pytest-provided temp directory for the SQLite file.
        **kwargs: Extra keyword arguments forwarded to :class:`FlowEngine`.

    Returns:
        The engine and the callable registry backing skill/tool nodes.
    """
    store = SQLiteStore(f"sqlite:///{tmp_path / 'flows.db'}")
    callables = CallableRegistry()
    engine = FlowEngine(
        store=store,
        handlers=build_default_handlers(store=store, callables=callables),
        **kwargs,
    )
    return engine, callables


def _child_flow(
    flow_id: str = "autodev/flow-child",
    budgets: dict[str, Any] | None = None,
    two_nodes: bool = False,
) -> dict[str, Any]:
    """A child flow transforming ``value`` through one (or two) skill nodes.

    Args:
        flow_id: Flow id to register the child under.
        budgets: Optional explicit budgets for the child manifest.
        two_nodes: Whether to chain a second transform node.

    Returns:
        The raw ``flow.yaml`` document.
    """
    nodes: list[dict[str, Any]] = [
        {
            "id": "transform",
            "type": "skill",
            "ref": "autodev/skill-transform",
            "input": {"value": "{{ flow.input.value }}"},
        }
    ]
    edges: list[dict[str, Any]] = []
    if two_nodes:
        nodes.append(
            {
                "id": "transform-again",
                "type": "skill",
                "ref": "autodev/skill-transform",
                "input": {"value": "{{ nodes.transform.output.transformed }}"},
            }
        )
        edges.append({"from": "transform", "to": "transform-again"})
    raw: dict[str, Any] = {
        "schemaVersion": "1",
        "id": flow_id,
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "input": {
            "type": "object",
            "required": ["value"],
            "properties": {"value": {}},
        },
        "nodes": nodes,
        "edges": edges,
    }
    if budgets is not None:
        raw["budgets"] = budgets
    return raw


def _subflow_parent(
    child_id: str = "autodev/flow-child",
    budgets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A parent flow with a single ``subflow`` node referencing ``child_id``."""
    raw: dict[str, Any] = {
        "schemaVersion": "1",
        "id": "autodev/flow-parent",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "input": {
            "type": "object",
            "required": ["value"],
            "properties": {"value": {}},
        },
        "nodes": [
            {
                "id": "sub",
                "type": "subflow",
                "ref": child_id,
                "input": {"value": "{{ flow.input.value }}"},
            }
        ],
        "edges": [],
    }
    if budgets is not None:
        raw["budgets"] = budgets
    return raw


def _map_parent(
    child_id: str = "autodev/flow-child",
    max_parallel: int | None = None,
    budgets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A parent flow with a single ``map`` node fanning ``child_id`` out."""
    node: dict[str, Any] = {
        "id": "fan",
        "type": "map",
        "ref": child_id,
        "over": "{{ flow.input.items }}",
        "input": {"value": "{{ item }}"},
    }
    if max_parallel is not None:
        node["maxParallel"] = max_parallel
    raw: dict[str, Any] = {
        "schemaVersion": "1",
        "id": "autodev/flow-map",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "input": {
            "type": "object",
            "required": ["items"],
            "properties": {"items": {"type": "array"}},
        },
        "nodes": [node],
        "edges": [],
    }
    if budgets is not None:
        raw["budgets"] = budgets
    return raw


def _register_transform(callables: CallableRegistry) -> None:
    """Register the upper-casing transform skill used by child flows."""

    def transform(payload: dict[str, Any]) -> dict[str, Any]:
        return {"transformed": str(payload["value"]).upper()}

    callables.register("autodev/skill-transform", transform)


def _costly_skill_handler(cost_usd: float) -> Any:
    """Build a skill handler reporting a fixed cost per activation.

    Args:
        cost_usd: Cost charged against the run budget per activation.

    Returns:
        A node handler producing ``{"transformed": ...}`` with cost metrics.
    """

    def handler(ctx: NodeContext) -> NodeOutcome:
        value = ctx.input.get("value", "")
        return NodeOutcome(
            output={"transformed": str(value).upper()},
            metrics={"cost_usd": cost_usd},
        )

    return handler


class TestSubflow:
    """Nested sub-flow execution (E3-S5-T1)."""

    def test_subflow_executes_and_links_child(self, tmp_path: Path) -> None:
        """The parent completes with the child's output plus childRunId."""
        engine, callables = _engine(tmp_path)
        _register_transform(callables)
        engine.registry.register_raw(_child_flow())
        engine.registry.register_raw(_subflow_parent())

        run = engine.start_run("autodev/flow-parent", input={"value": "ship"})

        assert run.status == "completed"
        assert run.output is not None
        assert run.output["transformed"] == "SHIP"
        children = engine.runs.list_runs(parent_run_id=run.run_id)
        assert len(children) == 1
        child = children[0]
        assert child.flow_id == "autodev/flow-child"
        assert child.status == "completed"
        assert child.parent_run_id == run.run_id
        assert run.output["childRunId"] == child.run_id
        steps = engine.runs.list_steps(run.run_id)
        assert steps[0].node_id == "sub"
        assert steps[0].output is not None
        assert steps[0].output["childRunId"] == child.run_id

    def test_child_failure_fails_parent_closed(self, tmp_path: Path) -> None:
        """A failing child run fails the parent step and run (fail closed)."""
        engine, callables = _engine(tmp_path)

        def boom(payload: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("kaput")

        callables.register("autodev/skill-transform", boom)
        engine.registry.register_raw(_child_flow())
        engine.registry.register_raw(_subflow_parent())

        run = engine.start_run("autodev/flow-parent", input={"value": "ship"})

        assert run.status == "failed"
        assert run.stop_reason == "node_failed"
        children = engine.runs.list_runs(parent_run_id=run.run_id)
        assert len(children) == 1 and children[0].status == "failed"
        steps = engine.runs.list_steps(run.run_id)
        assert steps[-1].status == "failed"
        assert children[0].run_id in steps[-1].error

    def test_unknown_flow_ref_fails_closed(self, tmp_path: Path) -> None:
        """A subflow ref that matches no registered flow fails the run."""
        engine, callables = _engine(tmp_path)
        _register_transform(callables)
        engine.registry.register_raw(_subflow_parent("autodev/flow-missing"))

        run = engine.start_run("autodev/flow-parent", input={"value": "ship"})

        assert run.status == "failed"
        assert run.stop_reason == "node_failed"
        steps = engine.runs.list_steps(run.run_id)
        assert "does not match a registered flow" in steps[-1].error


class TestMapReduce:
    """Parallel map fan-out and collect reduction (E3-S5-T2)."""

    def test_map_fans_out_and_collects_in_input_order(self, tmp_path: Path) -> None:
        """Map runs one child per item and collects outputs in input order."""
        engine, callables = _engine(tmp_path)
        _register_transform(callables)
        engine.registry.register_raw(_child_flow())
        engine.registry.register_raw(_map_parent(max_parallel=3))

        items = ["a", "b", "c", "d", "e"]
        run = engine.start_run("autodev/flow-map", input={"items": items})

        assert run.status == "completed"
        assert run.output is not None
        assert run.output["count"] == 5
        assert run.output["items"] == [
            {"transformed": item.upper()} for item in items
        ]
        child_run_ids = run.output["childRunIds"]
        assert len(child_run_ids) == 5
        assert len(set(child_run_ids)) == 5
        children = engine.runs.list_runs(parent_run_id=run.run_id)
        assert len(children) == 5
        assert {child.run_id for child in children} == set(child_run_ids)
        assert all(child.status == "completed" for child in children)
        steps = engine.runs.list_steps(run.run_id)
        assert steps[0].node_id == "fan"
        assert steps[0].output is not None
        assert steps[0].output["childRunIds"] == child_run_ids

    def test_max_parallel_bounds_concurrency(self, tmp_path: Path) -> None:
        """No more than maxParallel child branches run simultaneously."""
        engine, callables = _engine(tmp_path)
        lock = threading.Lock()
        active = 0
        peak = 0

        def tracking(payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {"transformed": str(payload["value"]).upper()}

        callables.register("autodev/skill-transform", tracking)
        engine.registry.register_raw(_child_flow())
        engine.registry.register_raw(_map_parent(max_parallel=2))

        run = engine.start_run(
            "autodev/flow-map", input={"items": ["a", "b", "c", "d", "e", "f"]}
        )

        assert run.status == "completed"
        assert peak <= 2

    def test_over_must_yield_a_list(self, tmp_path: Path) -> None:
        """A non-list ``over`` result fails the map step closed."""
        engine, callables = _engine(tmp_path)
        _register_transform(callables)
        engine.registry.register_raw(_child_flow())
        engine.registry.register_raw(_map_parent())

        run = engine.start_run("autodev/flow-map", input={"items": "not-a-list"})

        assert run.status == "failed"
        assert run.stop_reason == "node_failed"
        steps = engine.runs.list_steps(run.run_id)
        assert "'over' must yield a list" in steps[-1].error


    def test_map_bindings_may_compare_items(self, tmp_path: Path) -> None:
        """Ordering comparisons on ``item`` are valid map bindings.

        The engine must not pre-render map bindings (``item`` only exists
        inside the handler's fan-out), so an expression that would fail
        without ``item`` in scope still executes per item.
        """
        engine, callables = _engine(tmp_path)
        _register_transform(callables)
        engine.registry.register_raw(_child_flow())
        raw = _map_parent(max_parallel=1)
        raw["nodes"][0]["input"] = {"value": "{{ item > 2 }}"}
        engine.registry.register_raw(raw)

        run = engine.start_run("autodev/flow-map", input={"items": [1, 3]})

        assert run.status == "completed"
        assert run.output is not None
        assert [o["transformed"] for o in run.output["items"]] == [
            "FALSE",
            "TRUE",
        ]


class TestBudgetPropagation:
    """Parent budgets limit children and fail closed (E3-S5-T3, ADR-006)."""

    def test_map_aggregate_budget_fails_closed(self, tmp_path: Path) -> None:
        """Child spend beyond the parent budget stops the fan-out."""
        engine, _ = _engine(tmp_path)
        engine.handlers.register("skill", _costly_skill_handler(0.4))
        engine.registry.register_raw(_child_flow())
        engine.registry.register_raw(
            _map_parent(
                max_parallel=1,
                budgets={
                    "maxCostUsd": 1.0,
                    "maxWallClockSec": 60,
                    "maxTokens": 1000,
                },
            )
        )

        run = engine.start_run(
            "autodev/flow-map", input={"items": ["a", "b", "c", "d", "e"]}
        )

        assert run.status == "failed"
        assert run.stop_reason == "budget_exhausted"
        children = engine.runs.list_runs(parent_run_id=run.run_id)
        # Branches 0 and 1 fit (0.4 + 0.4); branch 2 is capped at the 0.2
        # remainder and fails closed; branches 3 and 4 never launch.
        assert len(children) == 3
        statuses = sorted(child.status for child in children)
        assert statuses == ["completed", "completed", "failed"]
        failed = [child for child in children if child.status == "failed"]
        assert failed[0].stop_reason == "budget_exhausted"

    def test_parallel_branches_cannot_jointly_overspend(
        self, tmp_path: Path
    ) -> None:
        """Concurrent branches reserve budget shares up front (fail closed).

        Without in-flight reservations, two parallel branches would each be
        capped at the full remaining budget and could jointly spend twice it
        before the post-completion check fires.
        """
        engine, _ = _engine(tmp_path)
        engine.handlers.register("skill", _costly_skill_handler(0.4))
        engine.registry.register_raw(_child_flow())
        engine.registry.register_raw(
            _map_parent(
                max_parallel=2,
                budgets={
                    "maxCostUsd": 0.5,
                    "maxWallClockSec": 60,
                    "maxTokens": 1000,
                },
            )
        )

        run = engine.start_run("autodev/flow-map", input={"items": ["a", "b"]})

        assert run.status == "failed"
        assert run.stop_reason == "budget_exhausted"
        children = engine.runs.list_runs(parent_run_id=run.run_id)
        # Each branch was reserved 0.25 (0.5 / 2 slots); a 0.4 spend breaches
        # its own cap, so neither branch can complete over budget.
        assert children and all(
            child.status == "failed"
            and child.stop_reason == "budget_exhausted"
            for child in children
        )

    def test_subflow_child_capped_below_own_manifest(self, tmp_path: Path) -> None:
        """A child is capped at the parent's remainder, not its own budget."""
        engine, _ = _engine(tmp_path)
        engine.handlers.register("skill", _costly_skill_handler(0.6))
        engine.registry.register_raw(
            _child_flow(
                budgets={
                    "maxCostUsd": 5.0,
                    "maxWallClockSec": 60,
                    "maxTokens": 1000,
                },
                two_nodes=True,
            )
        )
        engine.registry.register_raw(
            _subflow_parent(
                budgets={
                    "maxCostUsd": 0.5,
                    "maxWallClockSec": 60,
                    "maxTokens": 1000,
                }
            )
        )

        run = engine.start_run("autodev/flow-parent", input={"value": "ship"})

        assert run.status == "failed"
        assert run.stop_reason == "budget_exhausted"
        children = engine.runs.list_runs(parent_run_id=run.run_id)
        assert len(children) == 1
        child = children[0]
        # Under its own 5.0 USD manifest budget the child (2 x 0.6) would
        # complete; the parent's 0.5 USD remainder caps it after one node.
        assert child.status == "failed"
        assert child.stop_reason == "budget_exhausted"
        assert len(engine.runs.list_steps(child.run_id)) == 1


class TestNestedSubflow:
    """Depth-2 nesting works; recursion fails closed at the depth cap."""

    def test_nested_subflow_depth_two_links_correctly(self, tmp_path: Path) -> None:
        """parent -> mid -> leaf executes and links each level."""
        engine, callables = _engine(tmp_path)
        _register_transform(callables)
        engine.registry.register_raw(_child_flow("autodev/flow-leaf"))
        mid = _subflow_parent("autodev/flow-leaf")
        mid["id"] = "autodev/flow-mid"
        engine.registry.register_raw(mid)
        engine.registry.register_raw(_subflow_parent("autodev/flow-mid"))

        run = engine.start_run("autodev/flow-parent", input={"value": "ship"})

        assert run.status == "completed"
        assert run.output is not None
        assert run.output["transformed"] == "SHIP"
        mid_children = engine.runs.list_runs(parent_run_id=run.run_id)
        assert len(mid_children) == 1
        mid_run = mid_children[0]
        assert mid_run.flow_id == "autodev/flow-mid"
        assert run.output["childRunId"] == mid_run.run_id
        leaf_children = engine.runs.list_runs(parent_run_id=mid_run.run_id)
        assert len(leaf_children) == 1
        assert leaf_children[0].flow_id == "autodev/flow-leaf"
        assert mid_run.output is not None
        assert mid_run.output["childRunId"] == leaf_children[0].run_id

    def test_recursive_subflow_fails_closed_at_depth_cap(
        self, tmp_path: Path
    ) -> None:
        """A self-referencing sub-flow stops at MAX_COMPOSITE_DEPTH."""
        engine, callables = _engine(tmp_path)
        _register_transform(callables)
        loop = _subflow_parent("autodev/flow-loop")
        loop["id"] = "autodev/flow-loop"
        engine.registry.register_raw(loop)

        run = engine.start_run("autodev/flow-loop", input={"value": "ship"})

        assert run.status == "failed"
        assert run.stop_reason == "node_failed"
        all_runs = engine.runs.list_runs(flow_id="autodev/flow-loop")
        assert len(all_runs) == MAX_COMPOSITE_DEPTH + 1
        assert all(record.status == "failed" for record in all_runs)
        errors = [
            step.error
            for record in all_runs
            for step in engine.runs.list_steps(record.run_id)
            if step.status == "failed"
        ]
        assert any("max composite depth" in error for error in errors)
