"""E3-S4 tests: human-in-the-loop pause/decision/resume, timeout, durability."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient

from backend.config.settings import reset_settings_cache
from backend.flows.engine import FlowEngine
from backend.flows.handlers import CallableRegistry, build_default_handlers
from backend.flows.human import (
    FlowHumanDecisionError,
    FlowHumanService,
    FlowHumanStateError,
)
from backend.persistence.database import reset_store_cache
from backend.persistence.sqlite_adapter import SQLiteStore

START = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


def _review_flow(*, timeout: bool = False) -> dict[str, Any]:
    """A work -> review(human) flow routing on the decision (and timeout)."""
    nodes: list[dict[str, Any]] = [
        {"id": "prepare", "type": "skill", "ref": "autodev/skill-prepare"},
        {"id": "work", "type": "skill", "ref": "autodev/skill-work"},
        {
            "id": "review",
            "type": "human",
            "prompt": "Approve the work output?",
            "form": {
                "type": "object",
                "required": ["decision"],
                "properties": {
                    "decision": {"type": "string"},
                    "edits": {"type": "object"},
                },
            },
        },
        {
            "id": "finish",
            "type": "skill",
            "ref": "autodev/skill-finish",
            "input": {"result": "{{ nodes.work.output.result }}"},
        },
    ]
    edges: list[dict[str, Any]] = [
        {"from": "prepare", "to": "work"},
        {"from": "work", "to": "review"},
        {
            "from": "review",
            "to": "finish",
            "when": "{{ nodes.review.output.decision == 'approve' }}",
        },
        {
            "from": "review",
            "to": "work",
            "when": "{{ nodes.review.output.decision == 'request-changes' }}",
        },
    ]
    if timeout:
        human = next(node for node in nodes if node["id"] == "review")
        human["timeoutSec"] = 60
        human["onTimeout"] = "escalate"
        nodes.append(
            {"id": "escalate", "type": "skill", "ref": "autodev/skill-escalate"}
        )
        edges.append({"from": "review", "to": "escalate", "on": "timeout"})
    return {
        "schemaVersion": "1",
        "id": "autodev/flow-review",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "nodes": nodes,
        "edges": edges,
    }


def _register_callables(callables: CallableRegistry) -> list[str]:
    """Register the review flow's skills, recording the execution order."""
    order: list[str] = []

    def prepare(payload: dict[str, Any]) -> dict[str, Any]:
        order.append("prepare")
        return {"prepared": True}

    def work(payload: dict[str, Any]) -> dict[str, Any]:
        order.append("work")
        return {"result": "draft"}

    def finish(payload: dict[str, Any]) -> dict[str, Any]:
        order.append("finish")
        return {"done": True, "result": payload.get("result")}

    def escalate(payload: dict[str, Any]) -> dict[str, Any]:
        order.append("escalate")
        return {"escalated": True}

    callables.register("autodev/skill-prepare", prepare)
    callables.register("autodev/skill-work", work)
    callables.register("autodev/skill-finish", finish)
    callables.register("autodev/skill-escalate", escalate)
    return order


def _engine(tmp_path: Path, **kwargs: Any) -> tuple[FlowEngine, CallableRegistry]:
    """Build an engine on a temp SQLite store with a callable registry."""
    store = SQLiteStore(f"sqlite:///{tmp_path / 'human.db'}")
    callables = CallableRegistry()
    engine = FlowEngine(
        store=store,
        handlers=build_default_handlers(store=store, callables=callables),
        **kwargs,
    )
    return engine, callables


class TestPauseAndDecision:
    """A flow pauses at a human node and resumes after a decision (T1/T2)."""

    def test_run_pauses_at_human_node(self, tmp_path: Path) -> None:
        """The run stops as waiting_human with durable pause metadata."""
        engine, callables = _engine(tmp_path)
        _register_callables(callables)
        engine.registry.register_raw(_review_flow())

        run = engine.start_run("autodev/flow-review")

        assert run.status == "waiting_human"
        assert run.state["cursor"] == "review"
        assert run.state["pause"]["nodeId"] == "review"
        steps = engine.runs.list_steps(run.run_id)
        assert [(s.node_id, s.status) for s in steps] == [
            ("prepare", "completed"),
            ("work", "completed"),
            ("review", "waiting_human"),
        ]
        names = [event.name for event in engine.runs.list_events(run.run_id)]
        assert names[-1] == "flow.run.paused"

    def test_pending_decision_and_resume_to_completion(self, tmp_path: Path) -> None:
        """An approve decision records the output and completes the run."""
        engine, callables = _engine(tmp_path)
        _register_callables(callables)
        engine.registry.register_raw(_review_flow())
        run = engine.start_run("autodev/flow-review")
        service = FlowHumanService(engine=engine)

        pending = service.pending(run.run_id)
        assert pending is not None
        assert pending.node_id == "review"
        assert pending.prompt == "Approve the work output?"
        assert pending.form is not None and pending.expires_at is None

        result = service.decide(
            run.run_id, {"decision": "approve"}, actor="alice"
        )

        assert result.status == "completed"
        assert result.output == {"done": True, "result": "draft"}
        assert result.state["nodes"]["review"]["output"] == {"decision": "approve"}
        steps = {s.node_id: s for s in engine.runs.list_steps(run.run_id)}
        assert steps["review"].status == "completed"
        assert steps["review"].output == {"decision": "approve"}
        events = engine.runs.list_events(run.run_id)
        decision_events = [
            e for e in events if e.name == "flow.human.decision.recorded"
        ]
        assert len(decision_events) == 1
        assert decision_events[0].payload["actor"] == "alice"
        assert decision_events[0].payload["nodeId"] == "review"
        assert decision_events[0].payload["decision"] == {"decision": "approve"}
        assert events[-1].name == "flow.run.completed"

    def test_decision_routes_rework_loop(self, tmp_path: Path) -> None:
        """A request-changes decision routes back to work and pauses again."""
        engine, callables = _engine(tmp_path)
        order = _register_callables(callables)
        engine.registry.register_raw(_review_flow())
        run = engine.start_run("autodev/flow-review")
        service = FlowHumanService(engine=engine)

        result = service.decide(run.run_id, {"decision": "request-changes"})

        assert result.status == "waiting_human"
        assert order == ["prepare", "work", "work"]

    def test_invalid_decision_fails_closed(self, tmp_path: Path) -> None:
        """Missing required fields and non-waiting runs are rejected."""
        engine, callables = _engine(tmp_path)
        _register_callables(callables)
        raw = _review_flow()
        human = next(node for node in raw["nodes"] if node["id"] == "review")
        human["form"]["additionalProperties"] = False
        engine.registry.register_raw(raw)
        run = engine.start_run("autodev/flow-review")
        service = FlowHumanService(engine=engine)

        with pytest.raises(FlowHumanDecisionError, match="missing required"):
            service.decide(run.run_id, {})
        with pytest.raises(FlowHumanDecisionError, match="unknown decision fields"):
            service.decide(run.run_id, {"decision": "approve", "extra": 1})
        with pytest.raises(FlowHumanDecisionError, match="unknown node"):
            service.decide(
                run.run_id, {"decision": "approve", "edits": {"nope": {}}}
            )

        service.decide(run.run_id, {"decision": "approve"})
        with pytest.raises(FlowHumanStateError):
            service.decide(run.run_id, {"decision": "approve"})


class TestHumanEdits:
    """Human edits alter state seen by downstream bindings (T2)."""

    def test_edit_changes_prior_node_output_for_downstream(
        self, tmp_path: Path
    ) -> None:
        """An edit to work's output is observed by finish's input binding."""
        engine, callables = _engine(tmp_path)
        _register_callables(callables)
        engine.registry.register_raw(_review_flow())
        run = engine.start_run("autodev/flow-review")
        service = FlowHumanService(engine=engine)

        result = service.decide(
            run.run_id,
            {"decision": "approve", "edits": {"work": {"result": "edited"}}},
            actor="bob",
        )

        assert result.status == "completed"
        assert result.state["nodes"]["work"]["output"] == {"result": "edited"}
        assert result.output == {"done": True, "result": "edited"}
        steps = {s.node_id: s for s in engine.runs.list_steps(run.run_id)}
        assert steps["finish"].input == {"result": "edited"}


class TestTimeout:
    """Timeout triggers the alternate route (T3)."""

    def test_expire_due_routes_through_timeout_edge(self, tmp_path: Path) -> None:
        """A due wait completes via the escalate node with a timeout event."""
        current = {"now": START}
        engine, callables = _engine(tmp_path, now=lambda: current["now"])
        order = _register_callables(callables)
        engine.registry.register_raw(_review_flow(timeout=True))
        run = engine.start_run("autodev/flow-review")

        assert run.status == "waiting_human"
        expires_at = run.state["pause"]["expiresAt"]
        assert datetime.fromisoformat(expires_at) == START + timedelta(seconds=60)

        service = FlowHumanService(engine=engine)
        assert service.expire_due() == []  # not due yet

        current["now"] = START + timedelta(seconds=120)
        assert service.expire_due() == [run.run_id]

        reloaded = engine.runs.get_run(run.run_id)
        assert reloaded is not None and reloaded.status == "completed"
        assert reloaded.state["nodes"]["review"]["output"] == {"timedOut": True}
        assert order == ["prepare", "work", "escalate"]
        names = [event.name for event in engine.runs.list_events(run.run_id)]
        assert "flow.human.timeout.expired" in names
        assert names[-1] == "flow.run.completed"

    def test_late_decision_after_expiry_takes_timeout_route(
        self, tmp_path: Path
    ) -> None:
        """decide() on an expired wait fails closed and routes the timeout."""
        current = {"now": START}
        engine, callables = _engine(tmp_path, now=lambda: current["now"])
        order = _register_callables(callables)
        engine.registry.register_raw(_review_flow(timeout=True))
        run = engine.start_run("autodev/flow-review")
        service = FlowHumanService(engine=engine)

        current["now"] = START + timedelta(seconds=61)
        with pytest.raises(FlowHumanDecisionError, match="expired"):
            service.decide(run.run_id, {"decision": "approve"})

        reloaded = engine.runs.get_run(run.run_id)
        assert reloaded is not None and reloaded.status == "completed"
        assert reloaded.state["nodes"]["review"]["output"] == {"timedOut": True}
        assert order == ["prepare", "work", "escalate"]
        names = [event.name for event in engine.runs.list_events(run.run_id)]
        assert "flow.human.timeout.expired" in names
        assert "flow.human.decision.recorded" not in names


class TestDurability:
    """Pause state survives restart: a fresh engine resumes the wait (NFR)."""

    def test_fresh_engine_on_same_store_completes_decision(
        self, tmp_path: Path
    ) -> None:
        """Engine A pauses; engine B (same SQLite file) decides and resumes."""
        engine_a, callables_a = _engine(tmp_path)
        _register_callables(callables_a)
        engine_a.registry.register_raw(_review_flow())
        run = engine_a.start_run("autodev/flow-review")
        assert run.status == "waiting_human"

        store_b = SQLiteStore(f"sqlite:///{tmp_path / 'human.db'}")
        callables_b = CallableRegistry()
        engine_b = FlowEngine(
            store=store_b,
            handlers=build_default_handlers(store=store_b, callables=callables_b),
        )
        _register_callables(callables_b)
        service = FlowHumanService(engine=engine_b)

        pending = service.pending(run.run_id)
        assert pending is not None and pending.node_id == "review"

        result = service.decide(run.run_id, {"decision": "approve"}, actor="ops")

        assert result.status == "completed"
        assert result.output == {"done": True, "result": "draft"}


@pytest.fixture()
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store.

    The app module is imported *before* patching ``DATABASE_URL`` because its
    first import runs ``load_dotenv(override=True)``, which would clobber the
    patched value with the repository's ``.env``. Both the settings and the
    store caches are then reset so the patched URL takes effect even when
    earlier tests already cached the process-wide settings singleton.
    """
    from backend.api.main import app

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    reset_settings_cache()
    reset_store_cache()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_settings_cache()
    reset_store_cache()


def _register_review_skills() -> None:
    """Override the API engine dependency with the review flow's skills."""
    from backend.api.main import app
    from backend.api.routers import flows as flows_router

    callables = CallableRegistry()
    _register_callables(callables)

    def engine_with_skills() -> FlowEngine:
        return FlowEngine(handlers=build_default_handlers(callables=callables))

    app.dependency_overrides[flows_router.get_flow_engine] = engine_with_skills


class TestHumanApi:
    """/v2/flows human-in-the-loop routes (pending, decision, expire)."""

    def test_pending_decision_and_resume(self, client: TestClient) -> None:
        """The API exposes the pause and resumes the run on a decision."""
        _register_review_skills()
        assert client.post("/v2/flows", json=_review_flow()).status_code == 201

        started = client.post("/v2/flows/autodev/flow-review/runs", json={})
        assert started.status_code == 201
        run = started.json()
        assert run["status"] == "waiting_human"
        run_id = run["runId"]

        pending = client.get(f"/v2/flows/runs/{run_id}/pending-human")
        assert pending.status_code == 200
        doc = pending.json()
        assert doc["schemaVersion"] == "1"
        assert doc["nodeId"] == "review"
        assert doc["prompt"] == "Approve the work output?"

        assert client.get("/v2/flows/runs/nope/pending-human").status_code == 404

        decided = client.post(
            f"/v2/flows/runs/{run_id}/human-decision",
            json={"decision": {"decision": "approve"}, "actor": "alice"},
        )
        assert decided.status_code == 200
        body = decided.json()
        assert body["status"] == "completed"
        assert body["output"] == {"done": True, "result": "draft"}
        assert [s["status"] for s in body["steps"]] == ["completed"] * 4

        # No longer waiting: pending and further decisions conflict.
        assert (
            client.get(f"/v2/flows/runs/{run_id}/pending-human").status_code == 409
        )
        again = client.post(
            f"/v2/flows/runs/{run_id}/human-decision",
            json={"decision": {"decision": "approve"}},
        )
        assert again.status_code == 409

        events = client.get(f"/v2/flows/runs/{run_id}/events").json()["events"]
        recorded = [e for e in events if e["name"] == "flow.human.decision.recorded"]
        assert len(recorded) == 1
        assert recorded[0]["payload"]["actor"] == "alice"

    def test_invalid_decision_rejected(self, client: TestClient) -> None:
        """Decisions violating the form schema return 422."""
        _register_review_skills()
        client.post("/v2/flows", json=_review_flow())
        run_id = client.post(
            "/v2/flows/autodev/flow-review/runs", json={}
        ).json()["runId"]

        missing = client.post(
            f"/v2/flows/runs/{run_id}/human-decision", json={"decision": {}}
        )
        assert missing.status_code == 422
        no_decision = client.post(
            f"/v2/flows/runs/{run_id}/human-decision", json={"actor": "alice"}
        )
        assert no_decision.status_code == 422

    def test_expire_endpoint_routes_due_waits(self, client: TestClient) -> None:
        """POST /human/expire routes due waits through their timeout edges."""
        _register_review_skills()
        client.post("/v2/flows", json=_review_flow(timeout=True))
        run_id = client.post(
            "/v2/flows/autodev/flow-review/runs", json={}
        ).json()["runId"]

        not_due = client.post("/v2/flows/human/expire", json={})
        assert not_due.status_code == 200
        assert not_due.json()["expired"] == []

        later = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
        due = client.post("/v2/flows/human/expire", json={"at": later})
        assert due.status_code == 200
        assert due.json()["expired"] == [run_id]

        run = client.get(f"/v2/flows/runs/{run_id}").json()
        assert run["status"] == "completed"
        events = client.get(f"/v2/flows/runs/{run_id}/events").json()["events"]
        assert "flow.human.timeout.expired" in [e["name"] for e in events]

    def test_decision_requires_api_token_when_configured(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RBAC: the decision route honors the platform bearer-token gate."""
        _register_review_skills()
        client.post("/v2/flows", json=_review_flow())
        run_id = client.post(
            "/v2/flows/autodev/flow-review/runs", json={}
        ).json()["runId"]

        monkeypatch.setenv("AUTODEV_API_TOKEN", "s3cret")

        denied = client.post(
            f"/v2/flows/runs/{run_id}/human-decision",
            json={"decision": {"decision": "approve"}, "actor": "alice"},
        )
        assert denied.status_code == 401

        allowed = client.post(
            f"/v2/flows/runs/{run_id}/human-decision",
            json={"decision": {"decision": "approve"}, "actor": "alice"},
            headers={"Authorization": "Bearer s3cret"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "completed"

        events = client.get(
            f"/v2/flows/runs/{run_id}/events",
            headers={"Authorization": "Bearer s3cret"},
        ).json()["events"]
        recorded = [e for e in events if e["name"] == "flow.human.decision.recorded"]
        assert recorded[0]["payload"]["actor"] == "alice"
