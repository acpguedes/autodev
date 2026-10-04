"""E63-S4 invariants: the chat entrypoint follows task intent and project state."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.flows import selection as selection_mod
from backend.flows.engine import FlowEngine
from backend.flows.records import FlowRunRecord
from backend.flows.registry import FlowRegistry
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache

BOOTSTRAP = "autodev/flow-project-bootstrap"
DELIVERY = "autodev/flow-feature-delivery"


def _flow(flow_id: str, requires: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "1",
        "id": flow_id,
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "purpose": f"purpose of {flow_id}",
        "whenToUse": "when needed",
        "requires": requires,
        "nodes": [{"id": "a", "type": "agent", "ref": "autodev/agent-coder"}],
        "edges": [],
    }


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    db = f"sqlite:///{tmp_path / 'e63.db'}"
    monkeypatch.setenv("DATABASE_URL", db)
    reset_store_cache()
    store = DurableStore(db)
    registry = FlowRegistry(store)
    registry.register_raw(_flow(BOOTSTRAP, {"populated": False}))
    registry.register_raw(_flow(DELIVERY, {"populated": True}))
    started: list[str] = []

    def fake_start_run(self: FlowEngine, flow_id: str, **kwargs: Any) -> FlowRunRecord:
        started.append(flow_id)
        return FlowRunRecord(
            run_id="engine-run", flow_id=flow_id, flow_version="1.0.0",
            tenant_id="default", status="completed", output={"ok": True},
        )

    monkeypatch.setattr(FlowEngine, "start_run", fake_start_run)
    events: list[str] = []

    def capture(event_type: str, **_: Any) -> None:
        events.append(event_type)

    monkeypatch.setattr("backend.orchestrator.service.events.emit_event", capture)
    monkeypatch.setattr("backend.flows.selection.emit_event", capture)
    root = tmp_path / "project"
    root.mkdir()
    yield {"store": store, "root": root, "started": started, "events": events, "monkeypatch": monkeypatch}
    reset_store_cache()


def _service(env: dict[str, Any]) -> OrchestratorService:
    return OrchestratorService(store=env["store"], project_root=env["root"])


def _choose(env: dict[str, Any], flow: str, seen: list[str] | None = None) -> None:
    def chooser(task: str, candidates: Any) -> Any:
        if seen is not None:
            seen.extend(c["id"] for c in candidates)
        return {"flow": flow, "input": {}}

    env["monkeypatch"].setattr(selection_mod, "llm_chooser", chooser)


def _event_names(env: dict[str, Any]) -> list[str]:
    return env["events"]


def test_small_change_in_populated_project_runs_no_bootstrap_and_no_architect(
    env: dict[str, Any],
) -> None:
    (env["root"] / "app.py").write_text("print('hi')\n")
    seen: list[str] = []
    _choose(env, BOOTSTRAP, seen)  # adversarial model
    service = _service(env)
    session = service.create_plan("Logs UI")
    result = service.handle_message(session.session_id, "add a button to view logs")
    assert BOOTSTRAP not in seen and BOOTSTRAP not in env["started"]
    assert "architect" not in [r.agent for r in result.results]
    assert result.status == "completed"
    assert "flow.selection.skipped" in _event_names(env)


def test_no_compatible_flow_executes_directly_and_completes(env: dict[str, Any]) -> None:
    (env["root"] / "app.py").write_text("x = 1\n")
    _choose(env, "none")
    service = _service(env)
    session = service.create_plan("Maintenance")
    result = service.handle_message(session.session_id, "fix the typo in the header")
    assert env["started"] == []
    assert result.status == "completed" and result.results


def test_empty_project_and_new_project_selects_bootstrap_flow(env: dict[str, Any]) -> None:
    _choose(env, BOOTSTRAP)
    service = _service(env)
    session = service.create_plan("Start")
    result = service.handle_message(session.session_id, "create a new project")
    assert env["started"] == [BOOTSTRAP]
    assert result.status == "completed"
    assert result.results[0].agent == "flow"
    names = _event_names(env)
    assert "flow.run.started" in names and "flow.selection.matched" in names
