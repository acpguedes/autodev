"""E3-S2 API tests: /v2/flows registration, runs, triggers, events, e2e."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Generator, cast

import pytest
from fastapi.testclient import TestClient

from backend.persistence.database import reset_store_cache

PLUGIN_DIR = Path("examples/plugins/agent-coder")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    reset_store_cache()
    from backend.api.main import app

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_store_cache()


def _skill_flow() -> dict[str, Any]:
    """A minimal single-skill flow used across API tests."""
    return {
        "schemaVersion": "1",
        "id": "autodev/flow-api",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "triggers": [{"type": "message"}, {"type": "cron", "schedule": "* * * * *"}],
        "nodes": [{"id": "only", "type": "skill", "ref": "autodev/skill-echo"}],
        "edges": [],
    }


def _register_echo_skill() -> None:
    """Register the echo skill on the default handler registry.

    The API builds a fresh engine per request against the process-wide store;
    skills/tools registered through :class:`CallableRegistry` are in-process,
    so tests register them on the module-level default used by the router.
    """
    from backend.api.routers import flows as flows_router
    from backend.flows.handlers import CallableRegistry, build_default_handlers
    from backend.flows.engine import FlowEngine

    callables = CallableRegistry()
    callables.register("autodev/skill-echo", lambda payload: {"echo": payload})

    def engine_with_echo() -> FlowEngine:
        return FlowEngine(handlers=build_default_handlers(callables=callables))

    from backend.api.main import app

    app.dependency_overrides[flows_router.get_flow_engine] = engine_with_echo


class TestFlowRegistrationApi:
    """Register, validate, and list flows through /v2/flows."""

    def test_register_list_and_versions(self, client: TestClient) -> None:
        """A valid manifest registers and shows up in catalog and versions."""
        response = client.post("/v2/flows", json=_skill_flow())
        assert response.status_code == 201
        assert response.json()["registered"] == {
            "id": "autodev/flow-api",
            "version": "1.0.0",
        }

        catalog = client.get("/v2/flows").json()
        assert catalog["schemaVersion"] == "1"
        assert [flow["id"] for flow in catalog["flows"]] == ["autodev/flow-api"]

        versions = client.get("/v2/flows/autodev/flow-api").json()
        assert versions["versions"] == [{"version": "1.0.0", "name": None}]

    def test_invalid_manifest_rejected_with_errors(self, client: TestClient) -> None:
        """Invalid manifests return 422 with the full error list."""
        raw = _skill_flow()
        raw["nodes"] = []
        response = client.post("/v2/flows", json=raw)
        assert response.status_code == 422
        assert any("at least one node" in e for e in response.json()["detail"]["errors"])

        validate = client.post("/v2/flows/validate", json=raw).json()
        assert validate["valid"] is False
        assert validate["errors"]

    def test_unknown_flow_404(self, client: TestClient) -> None:
        """Unknown flows return 404 on versions and run start."""
        assert client.get("/v2/flows/autodev/nope").status_code == 404
        assert (
            client.post("/v2/flows/autodev/nope/runs", json={"input": {}}).status_code
            == 404
        )


class TestFlowRunsApi:
    """Start runs and read run state/events through the API."""

    def test_run_start_steps_and_events(self, client: TestClient) -> None:
        """POST /runs executes and exposes steps and the event store."""
        _register_echo_skill()
        client.post("/v2/flows", json=_skill_flow())

        started = time.perf_counter()
        response = client.post(
            "/v2/flows/autodev/flow-api/runs", json={"input": {"x": 1}}
        )
        elapsed = time.perf_counter() - started

        assert response.status_code == 201
        run = response.json()
        assert run["status"] == "completed"
        assert run["steps"][0]["nodeId"] == "only"
        assert elapsed < 1.0, "run start must begin streaming results in < 1 s"

        fetched = client.get(f"/v2/flows/runs/{run['runId']}").json()
        assert fetched["status"] == "completed"
        assert [step["status"] for step in fetched["steps"]] == ["completed"]

        events = client.get(f"/v2/flows/runs/{run['runId']}/events").json()["events"]
        assert [event["name"] for event in events] == [
            "flow.run.started",
            "run.step.started",
            "run.step.completed",
            "flow.run.completed",
        ]

    def test_declared_trigger_and_undeclared_trigger(self, client: TestClient) -> None:
        """/trigger honors declared trigger types and fails closed otherwise."""
        _register_echo_skill()
        client.post("/v2/flows", json=_skill_flow())

        ok = client.post(
            "/v2/flows/autodev/flow-api/trigger",
            json={"type": "message", "input": {}, "payload": {"text": "go"}},
        )
        assert ok.status_code == 201
        assert ok.json()["trigger"]["type"] == "message"

        denied = client.post(
            "/v2/flows/autodev/flow-api/trigger",
            json={"type": "webhook", "input": {}},
        )
        assert denied.status_code == 422

    def test_cron_tick_starts_due_runs(self, client: TestClient) -> None:
        """/cron/tick starts runs for flows with due cron schedules."""
        _register_echo_skill()
        client.post("/v2/flows", json=_skill_flow())

        response = client.post(
            "/v2/flows/cron/tick", json={"at": "2026-07-06T10:00:00+00:00"}
        )
        assert response.status_code == 200
        started = response.json()["started"]
        assert len(started) == 1
        assert started[0]["flowId"] == "autodev/flow-api"

        run = client.get(f"/v2/flows/runs/{started[0]['runId']}").json()
        assert run["trigger"]["type"] == "cron"


class TestAgentFlowEndToEnd:
    """Alpha-gate slice: a declarative flow executes an agent-plugin."""

    def test_flow_executes_agent_coder_plugin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A flow.yaml agent node runs autodev/agent-coder with durable state."""
        from backend.agents.registry_v2 import AgentRegistry
        from backend.flows.engine import FlowEngine
        from backend.flows.handlers import AgentNodeHandler, build_default_handlers
        from backend.persistence.sqlite_adapter import SQLiteStore
        from backend.plugins.host import PluginHost

        store = SQLiteStore(f"sqlite:///{tmp_path / 'e2e.db'}")
        host = PluginHost(store=store)
        host.install(PLUGIN_DIR)
        host.enable("autodev/agent-coder")
        registry = AgentRegistry(store)
        registry.sync_from_plugin_store()

        agent_handler = AgentNodeHandler(agent_registry=registry, store=store)
        engine = FlowEngine(
            store=store,
            handlers=build_default_handlers(store=store, agent_handler=agent_handler),
        )
        engine.registry.register_raw(
            {
                "schemaVersion": "1",
                "id": "autodev/flow-code",
                "version": "1.0.0",
                "hostApi": ">=2.0 <3.0",
                "input": {
                    "type": "object",
                    "required": ["goal"],
                    "properties": {"goal": {"type": "string"}},
                },
                "nodes": [
                    {
                        "id": "code",
                        "type": "agent",
                        "ref": "autodev/agent-coder@>=1.0 <2.0",
                        "input": {
                            "schemaVersion": "1.0.0",
                            "task": {
                                "goal": "{{ flow.input.goal }}",
                                "userRequest": "{{ flow.input.goal }}",
                                "plan": ["Expose schemas", "Add tests"],
                            },
                            "context": {},
                        },
                    }
                ],
                "edges": [],
            }
        )

        run = engine.start_run(
            "autodev/flow-code", input={"goal": "Expose agent contracts"}
        )

        assert run.status == "completed"
        output = cast(dict[str, Any], run.output)
        assert output["schemaVersion"] == "1.0.0"
        assert output["codingTasks"]
        steps = engine.runs.list_steps(run.run_id)
        assert [step.node_type for step in steps] == ["agent"]
        events = [event.name for event in engine.runs.list_events(run.run_id)]
        assert events == [
            "flow.run.started",
            "run.step.started",
            "run.step.completed",
            "flow.run.completed",
        ]
