"""E3-S3 tests: checkpoints, retry/backoff, crash recovery, deterministic replay."""

from __future__ import annotations

import json
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

import pytest

from backend.flows.engine import FlowEngine, FlowRunError
from backend.flows.handlers import CallableRegistry, build_default_handlers
from backend.persistence.sqlite_adapter import SQLiteStore


class SimulatedCrash(KeyboardInterrupt):
    """Process-death stand-in: ``except Exception`` does not catch it.

    Raising it from a node handler leaves the run ``running`` with a
    persisted cursor and an orphaned ``running`` step — exactly the durable
    state a killed worker process leaves behind.
    """


def _build_engine(
    tmp_path: Path,
    *,
    db: str = "flows.db",
    sleeper: Callable[[float], None] | None = None,
) -> tuple[SQLiteStore, FlowEngine, CallableRegistry]:
    """Build an engine on a temp SQLite store with a callable registry.

    Args:
        tmp_path: Pytest temp directory hosting the SQLite file.
        db: Database file name (reuse the same name to simulate restarts).
        sleeper: Backoff sleeper; defaults to a no-op so tests do not wait.

    Returns:
        The store, the engine, and the callable registry backing skills.
    """
    store = SQLiteStore(f"sqlite:///{tmp_path / db}")
    callables = CallableRegistry()
    engine = FlowEngine(
        store=store,
        handlers=build_default_handlers(store=store, callables=callables),
        sleeper=sleeper or (lambda _delay: None),
    )
    return store, engine, callables


def _linear_flow(flow_id: str = "autodev/flow-linear") -> dict[str, Any]:
    """A three-skill pipeline with a conditional rework loop (as in E3-S2)."""
    return {
        "schemaVersion": "1",
        "id": flow_id,
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
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


def _retry_flow(
    retries: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A two-skill flow whose first node carries an optional retry override."""
    flaky: dict[str, Any] = {
        "id": "flaky",
        "type": "skill",
        "ref": "autodev/skill-flaky",
    }
    if retries is not None:
        flaky["retries"] = retries
    raw: dict[str, Any] = {
        "schemaVersion": "1",
        "id": "autodev/flow-retry",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "nodes": [
            flaky,
            {"id": "finish", "type": "skill", "ref": "autodev/skill-finish"},
        ],
        "edges": [{"from": "flaky", "to": "finish"}],
    }
    if defaults is not None:
        raw["defaults"] = defaults
    return raw


def _register_flaky(
    callables: CallableRegistry, fail_times: int
) -> dict[str, int]:
    """Register a skill failing ``fail_times`` times before succeeding.

    Args:
        callables: Registry to install the skills into.
        fail_times: Invocations that raise before the first success.

    Returns:
        A mutable counter dict tracking invocations per skill.
    """
    counts = {"flaky": 0, "finish": 0}

    def flaky(payload: dict[str, Any]) -> dict[str, Any]:
        counts["flaky"] += 1
        if counts["flaky"] <= fail_times:
            raise RuntimeError(f"transient failure {counts['flaky']}")
        return {"ok": True}

    def finish(payload: dict[str, Any]) -> dict[str, Any]:
        counts["finish"] += 1
        return {"done": True}

    callables.register("autodev/skill-flaky", flaky)
    callables.register("autodev/skill-finish", finish)
    return counts


class TestRetryBackoff:
    """Retry honors the manifest policy with per-attempt steps (E3-S3-T2)."""

    def test_fixed_backoff_retries_until_success(self, tmp_path: Path) -> None:
        """Two failures under maxAttempts=3/fixed sleep 0.5 s each, then pass."""
        sleeps: list[float] = []
        _, engine, callables = _build_engine(tmp_path, sleeper=sleeps.append)
        counts = _register_flaky(callables, fail_times=2)
        engine.registry.register_raw(
            _retry_flow({"maxAttempts": 3, "backoff": "fixed", "initialDelaySec": 0.5})
        )

        run = engine.start_run("autodev/flow-retry")

        assert run.status == "completed"
        assert run.output == {"done": True}
        assert counts["flaky"] == 3
        assert sleeps == [0.5, 0.5]
        steps = [s for s in engine.runs.list_steps(run.run_id) if s.node_id == "flaky"]
        assert [s.attempt for s in steps] == [1, 2, 3]
        assert [s.status for s in steps] == ["failed", "failed", "completed"]
        names = [e.name for e in engine.runs.list_events(run.run_id)]
        assert names.count("run.step.failed") == 2

    def test_exponential_backoff_doubles_delay(self, tmp_path: Path) -> None:
        """Exponential backoff sleeps initialDelaySec * 2^(attempt-1)."""
        sleeps: list[float] = []
        _, engine, callables = _build_engine(tmp_path, sleeper=sleeps.append)
        _register_flaky(callables, fail_times=2)
        engine.registry.register_raw(
            _retry_flow(
                {"maxAttempts": 3, "backoff": "exponential", "initialDelaySec": 0.5}
            )
        )

        run = engine.start_run("autodev/flow-retry")

        assert run.status == "completed"
        assert sleeps == [0.5, 1.0]

    def test_exhausted_attempts_fail_the_run(self, tmp_path: Path) -> None:
        """Only the final failed attempt fails the run; no sleep after it."""
        sleeps: list[float] = []
        _, engine, callables = _build_engine(tmp_path, sleeper=sleeps.append)
        counts = _register_flaky(callables, fail_times=99)
        engine.registry.register_raw(
            _retry_flow({"maxAttempts": 2, "backoff": "fixed", "initialDelaySec": 0.1})
        )

        run = engine.start_run("autodev/flow-retry")

        assert run.status == "failed"
        assert run.stop_reason == "node_failed"
        assert counts["flaky"] == 2 and counts["finish"] == 0
        assert sleeps == [0.1]
        steps = engine.runs.list_steps(run.run_id)
        assert [s.attempt for s in steps] == [1, 2]
        assert all(s.status == "failed" for s in steps)
        failed_events = [
            e for e in engine.runs.list_events(run.run_id)
            if e.name == "run.step.failed"
        ]
        assert [e.payload["willRetry"] for e in failed_events] == [True, False]
        # A failed run is terminal and therefore replayable: with no completed
        # steps the derived cursor stays at the entry node, as recorded.
        report = engine.replay_run(run.run_id)
        assert report.deterministic is True

    def test_flow_default_retries_apply_without_node_override(
        self, tmp_path: Path
    ) -> None:
        """defaults.retries governs nodes that do not override retries."""
        sleeps: list[float] = []
        _, engine, callables = _build_engine(tmp_path, sleeper=sleeps.append)
        counts = _register_flaky(callables, fail_times=1)
        engine.registry.register_raw(
            _retry_flow(
                retries=None,
                defaults={
                    "retries": {
                        "maxAttempts": 2,
                        "backoff": "fixed",
                        "initialDelaySec": 0.0,
                    }
                },
            )
        )

        run = engine.start_run("autodev/flow-retry")

        assert run.status == "completed"
        assert counts["flaky"] == 2
        assert sleeps == [0.0]

    def test_unsupported_node_never_retries(self, tmp_path: Path) -> None:
        """UnsupportedNodeError fails closed on the first attempt."""
        sleeps: list[float] = []
        _, engine, callables = _build_engine(tmp_path, sleeper=sleeps.append)
        callables.register("autodev/skill-finish", lambda p: {"done": True})
        # autodev/skill-flaky is intentionally not registered.
        engine.registry.register_raw(
            _retry_flow({"maxAttempts": 3, "backoff": "fixed", "initialDelaySec": 0.5})
        )

        run = engine.start_run("autodev/flow-retry")

        assert run.status == "failed"
        assert run.stop_reason == "unsupported_node"
        assert sleeps == []
        assert len(engine.runs.list_steps(run.run_id)) == 1

    def test_backoff_sleep_respects_wall_clock_budget(self, tmp_path: Path) -> None:
        """A retry backoff that would breach the run budget fails closed.

        ``maxWallClockSec`` is set to its minimum (1s); a node with a large
        fixed backoff (60s) always fails, so the very first retry's backoff
        already breaches the budget and the run must fail with
        ``budget_exhausted`` before ever sleeping for 60s.
        """
        sleeps: list[float] = []
        _, engine, callables = _build_engine(tmp_path, sleeper=sleeps.append)
        callables.register(
            "autodev/skill-flaky",
            lambda p: (_ for _ in ()).throw(RuntimeError("always fails")),
        )
        callables.register("autodev/skill-finish", lambda p: {"done": True})
        flow = _retry_flow(
            {"maxAttempts": 3, "backoff": "fixed", "initialDelaySec": 60.0}
        )
        flow["budgets"] = {"maxWallClockSec": 1}
        engine.registry.register_raw(flow)

        run = engine.start_run("autodev/flow-retry")

        assert run.status == "failed"
        assert run.stop_reason == "budget_exhausted"
        assert 60.0 not in sleeps

    def test_non_serializable_output_fails_closed(self, tmp_path: Path) -> None:
        """A node output that cannot round-trip through JSON fails the run."""
        _, engine, callables = _build_engine(tmp_path)
        callables.register("autodev/skill-flaky", lambda p: {"bad": object()})
        callables.register("autodev/skill-finish", lambda p: {"done": True})
        engine.registry.register_raw(_retry_flow())

        run = engine.start_run("autodev/flow-retry")

        assert run.status == "failed"
        assert run.stop_reason == "node_failed"
        failed_events = [
            e for e in engine.runs.list_events(run.run_id)
            if e.name == "flow.run.failed"
        ]
        assert failed_events and "serializable" in failed_events[0].payload["detail"]
        steps = [s for s in engine.runs.list_steps(run.run_id) if s.node_id == "flaky"]
        assert steps[-1].status == "failed"


class TestCrashRecovery:
    """An interrupted run resumes from the last checkpoint (E3-S3-T1)."""

    def test_interrupted_run_resumes_without_reexecuting_steps(
        self, tmp_path: Path
    ) -> None:
        """A crash mid-run resumes on a fresh engine; done work is reused."""
        counts = {"prepare": 0, "work": 0, "finish": 0}

        def register(callables: CallableRegistry, crash_once: bool) -> None:
            """Install the linear flow's skills; ``work`` may crash once."""

            def prepare(payload: dict[str, Any]) -> dict[str, Any]:
                counts["prepare"] += 1
                return {"prepared": f"prep:{payload['task']}"}

            def work(payload: dict[str, Any]) -> dict[str, Any]:
                counts["work"] += 1
                if crash_once and counts["work"] == 1:
                    raise SimulatedCrash("process killed")
                return {"ok": True, "result": payload["prepared"].upper()}

            def finish(payload: dict[str, Any]) -> dict[str, Any]:
                counts["finish"] += 1
                return {"done": True}

            callables.register("autodev/skill-prepare", prepare)
            callables.register("autodev/skill-work", work)
            callables.register("autodev/skill-finish", finish)

        _, engine, callables = _build_engine(tmp_path)
        register(callables, crash_once=True)
        engine.registry.register_raw(_linear_flow())
        run = engine.start_run(
            "autodev/flow-linear", input={"task": "ship"}, execute=False
        )
        with pytest.raises(SimulatedCrash):
            engine.execute_run(run.run_id)

        crashed = engine.runs.get_run(run.run_id)
        assert crashed is not None and crashed.status == "running"
        assert crashed.state["cursor"] == "work"

        # Fresh engine on the same database, as after a process restart.
        _, second, callables2 = _build_engine(tmp_path)
        register(callables2, crash_once=False)
        resumed = second.resume_run(run.run_id)

        assert resumed.status == "completed"
        assert resumed.output == {"done": True}
        assert counts["prepare"] == 1, "completed steps must not re-execute"
        assert counts["work"] == 2 and counts["finish"] == 1
        assert resumed.state["nodes"]["prepare"]["output"] == {"prepared": "prep:ship"}

        steps = second.runs.list_steps(run.run_id)
        by_node = {node: [s for s in steps if s.node_id == node]
                   for node in ("prepare", "work", "gate", "finish")}
        assert len(by_node["prepare"]) == 1
        assert [s.status for s in by_node["work"]] == ["failed", "completed"]
        assert "interrupted" in by_node["work"][0].error
        events = [e.name for e in second.runs.list_events(run.run_id)]
        assert "flow.run.resumed" in events
        assert events[-1] == "flow.run.completed"
        prepare_starts = [
            e for e in second.runs.list_events(run.run_id)
            if e.name == "run.step.started" and e.payload["nodeId"] == "prepare"
        ]
        assert len(prepare_starts) == 1

    def test_resume_reconciles_crash_window_without_reexecuting(
        self, tmp_path: Path
    ) -> None:
        """A step completed but never routed/checkpointed is folded on resume.

        This simulates a crash between ``complete_step``'s commit and the
        state checkpoint: the entry node's step is durably ``completed``, but
        ``state.nodes`` was never updated and no ``run.step.completed`` event
        was appended. Resuming must fold the recorded output in and route
        past it instead of re-executing the node.
        """
        counts = {"prepare": 0, "work": 0, "finish": 0}
        _, engine, callables = _build_engine(tmp_path)

        def prepare(payload: dict[str, Any]) -> dict[str, Any]:
            counts["prepare"] += 1
            return {"prepared": "should-not-run"}

        def work(payload: dict[str, Any]) -> dict[str, Any]:
            counts["work"] += 1
            return {"ok": True, "result": payload["prepared"].upper()}

        def finish(payload: dict[str, Any]) -> dict[str, Any]:
            counts["finish"] += 1
            return {"done": True}

        callables.register("autodev/skill-prepare", prepare)
        callables.register("autodev/skill-work", work)
        callables.register("autodev/skill-finish", finish)
        engine.registry.register_raw(_linear_flow())

        run = engine.start_run(
            "autodev/flow-linear", input={"task": "ship"}, execute=False
        )
        assert run.state["cursor"] == "prepare"

        # Simulate the crash window: the step commit lands, the state
        # checkpoint and event do not.
        step = engine.runs.create_step(
            run_id=run.run_id,
            node_id="prepare",
            node_type="skill",
            attempt=1,
            input={"task": "ship"},
        )
        engine.runs.complete_step(
            step.step_id, status="completed", output={"prepared": "prep:ship"}
        )

        resumed = engine.resume_run(run.run_id)

        assert resumed.status == "completed"
        assert counts["prepare"] == 0, "reconciled node must not re-execute"
        assert counts["work"] == 1 and counts["finish"] == 1
        assert resumed.state["nodes"]["prepare"]["output"] == {
            "prepared": "prep:ship"
        }
        reconciled_events = [
            e
            for e in engine.runs.list_events(run.run_id)
            if e.name == "run.step.completed" and e.payload.get("nodeId") == "prepare"
        ]
        assert len(reconciled_events) == 1
        assert reconciled_events[0].payload["reconciled"] is True

    def test_resume_rejects_terminal_run(self, tmp_path: Path) -> None:
        """Resuming a completed run fails closed with FlowRunError."""
        _, engine, callables = _build_engine(tmp_path)
        _register_flaky(callables, fail_times=0)
        engine.registry.register_raw(_retry_flow())

        run = engine.start_run("autodev/flow-retry")

        assert run.status == "completed"
        with pytest.raises(FlowRunError, match="terminal"):
            engine.resume_run(run.run_id)

    def test_execute_run_is_idempotent_on_terminal_run(self, tmp_path: Path) -> None:
        """execute_run on a terminal run returns it unchanged, no new steps."""
        _, engine, callables = _build_engine(tmp_path)
        counts = _register_flaky(callables, fail_times=0)
        engine.registry.register_raw(_retry_flow())
        run = engine.start_run("autodev/flow-retry")
        steps_before = len(engine.runs.list_steps(run.run_id))
        events_before = len(engine.runs.list_events(run.run_id))

        again = engine.execute_run(run.run_id)

        assert again.status == "completed"
        assert counts["flaky"] == 1
        assert len(engine.runs.list_steps(run.run_id)) == steps_before
        assert len(engine.runs.list_events(run.run_id)) == events_before


class TestDeterministicReplay:
    """Replay reproduces decisions from persisted state alone (E3-S3-T3)."""

    def _run_with_rework_loop(
        self, tmp_path: Path
    ) -> tuple[SQLiteStore, FlowEngine, Any]:
        """Execute the linear flow taking the rework loop exactly once.

        Returns:
            The store, the engine, and the completed run record.
        """
        store, engine, callables = _build_engine(tmp_path)
        state = {"work_calls": 0}

        def work(payload: dict[str, Any]) -> dict[str, Any]:
            state["work_calls"] += 1
            return {"ok": state["work_calls"] > 1, "result": payload["prepared"]}

        callables.register(
            "autodev/skill-prepare", lambda p: {"prepared": f"prep:{p['task']}"}
        )
        callables.register("autodev/skill-work", work)
        callables.register("autodev/skill-finish", lambda p: {"done": True})
        engine.registry.register_raw(_linear_flow())
        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})
        assert run.status == "completed"
        return store, engine, run

    def test_identical_replay_reports_deterministic(self, tmp_path: Path) -> None:
        """Replaying an untouched trace matches the recorded sequence."""
        _, engine, run = self._run_with_rework_loop(tmp_path)

        report = engine.replay_run(run.run_id)

        expected = ("prepare", "work", "gate", "work", "gate", "finish")
        assert report.deterministic is True
        assert report.divergences == ()
        assert report.recorded_sequence == expected
        assert report.replayed_sequence == expected
        events = engine.runs.list_events(run.run_id)
        assert events[-1].name == "flow.run.replayed"
        assert events[-1].payload["deterministic"] is True

    def test_corrupted_step_output_reports_divergence(self, tmp_path: Path) -> None:
        """Tampering with a recorded output flips the derived routing."""
        store, engine, run = self._run_with_rework_loop(tmp_path)
        # Corrupt the SECOND (successful) work step so the gate predicate
        # would route back to `work` instead of `finish` on replay.
        with closing(store.connect()) as conn:
            conn.execute(
                """
                UPDATE flow_steps SET output_json = ?
                WHERE run_id = ? AND node_id = 'work'
                  AND status = 'completed'
                  AND sequence = (
                      SELECT MAX(sequence) FROM flow_steps
                      WHERE run_id = ? AND node_id = 'work'
                  )
                """,
                (
                    json.dumps({"ok": False, "result": "corrupted"}),
                    run.run_id,
                    run.run_id,
                ),
            )
            conn.commit()

        report = engine.replay_run(run.run_id)

        assert report.deterministic is False
        assert report.divergences
        assert report.recorded_sequence[-1] == "finish"
        assert report.replayed_sequence[-1] == "work"
        events = engine.runs.list_events(run.run_id)
        assert events[-1].name == "flow.run.replayed"
        assert events[-1].payload["deterministic"] is False

    def test_replay_requires_terminal_run(self, tmp_path: Path) -> None:
        """Non-terminal runs cannot be replayed (fail closed)."""
        _, engine, callables = _build_engine(tmp_path)
        _register_flaky(callables, fail_times=0)
        engine.registry.register_raw(_retry_flow())
        run = engine.start_run("autodev/flow-retry", execute=False)

        with pytest.raises(FlowRunError, match="not terminal"):
            engine.replay_run(run.run_id)

    def test_replay_reproduces_recorded_routing_failure(
        self, tmp_path: Path
    ) -> None:
        """A run that failed with no_route replays as deterministic."""
        _, engine, callables = _build_engine(tmp_path)
        callables.register(
            "autodev/skill-prepare", lambda p: {"prepared": f"prep:{p['task']}"}
        )
        # `ok` is neither true nor false, so no gate edge matches: no_route.
        callables.register("autodev/skill-work", lambda p: {"ok": "maybe"})
        callables.register("autodev/skill-finish", lambda p: {"done": True})
        engine.registry.register_raw(_linear_flow())
        run = engine.start_run("autodev/flow-linear", input={"task": "ship"})
        assert run.status == "failed" and run.stop_reason == "no_route"

        report = engine.replay_run(run.run_id)

        assert report.deterministic is True
        assert report.replayed_sequence == report.recorded_sequence


class TestCheckpointOverhead:
    """Checkpoint overhead stays bounded (E3-S3 NFR, CI-stable variant)."""

    def test_per_step_persistence_cost_is_bounded(self, tmp_path: Path) -> None:
        """Per-step checkpoint cost stays under a generous absolute bound.

        The story NFR is "checkpoint overhead < 10%". A strict ratio against
        pure handler time is meaningless here — no-op handlers make the
        denominator ~0 — and flaky in CI. Instead this asserts the absolute
        per-step cost of the built-in checkpointing (step rows, events, and
        the state_json write on SQLite/WAL) stays under 50 ms, which bounds
        checkpoint overhead below 10% for any node doing >= 0.5 s of real
        work; in practice LLM/tool nodes take seconds, so the effective
        overhead is far below the NFR. Best-of-three keeps the measurement
        stable on shared CI runners.
        """
        node_count = 20
        _, engine, callables = _build_engine(tmp_path)
        callables.register("autodev/skill-noop", lambda p: {"ok": True})
        nodes = [
            {"id": f"step-{i}", "type": "skill", "ref": "autodev/skill-noop"}
            for i in range(node_count)
        ]
        edges = [
            {"from": f"step-{i}", "to": f"step-{i + 1}"}
            for i in range(node_count - 1)
        ]
        engine.registry.register_raw(
            {
                "schemaVersion": "1",
                "id": "autodev/flow-chain",
                "version": "1.0.0",
                "hostApi": ">=2.0 <3.0",
                "nodes": nodes,
                "edges": edges,
            }
        )

        durations: list[float] = []
        for _ in range(3):
            started = time.perf_counter()
            run = engine.start_run("autodev/flow-chain")
            durations.append(time.perf_counter() - started)
            assert run.status == "completed"
            assert len(engine.runs.list_steps(run.run_id)) == node_count

        per_step = min(durations) / node_count
        assert per_step < 0.05, (
            f"checkpoint cost {per_step * 1000:.1f} ms/step exceeds the "
            "50 ms/step bound backing the <10% overhead NFR"
        )
