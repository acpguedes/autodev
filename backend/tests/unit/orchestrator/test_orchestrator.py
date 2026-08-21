"""Unit tests for the orchestrator service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, cast

import pytest

from backend.agents import AgentResult
from backend.agents.planner.agent import PlannerAgent
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache


@pytest.fixture()
def orchestrator_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[OrchestratorService]:
    database_path = tmp_path / "autodev-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    reset_store_cache()
    service = OrchestratorService(store=DurableStore(f"sqlite:///{database_path}"))
    yield service
    reset_store_cache()


def test_create_plan_generates_steps(orchestrator_service: OrchestratorService) -> None:
    session = orchestrator_service.create_plan("Implement orchestrator")

    assert session.session_id
    assert session.plan
    assert "Implement" in session.plan[0]
    assert session.status == "awaiting_input"


def test_handle_message_returns_agent_responses(orchestrator_service: OrchestratorService) -> None:
    session = orchestrator_service.create_plan("Ship MVP")

    result = orchestrator_service.handle_message(session.session_id, "Start execution")

    assert result.run_id
    assert result.status == "completed"
    assert result.run_type == "existing_repo_change"
    assert result.current_state == "completed"
    assert result.session_id == session.session_id
    agent_names = [execution.agent for execution in result.results]
    assert "navigator" in agent_names
    assert any("DevOps" in execution.content for execution in result.results)
    assert len(result.steps) == len(result.results)
    assert result.steps[0].step_key == "navigator"
    assert all(step.status == "completed" for step in result.steps)
    assert result.history[0].role == "user"
    assert result.history[0].content == "Start execution"
    assert all(entry.content for entry in result.history)


def test_handle_message_emits_live_timeline_events_per_agent(
    orchestrator_service: OrchestratorService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E43-S6: a Chat turn's agent graph now emits ``run.timeline.*`` events
    as each mapped agent completes, not just the final aggregate response --
    previously only the "Run plan" task-dispatch pipeline emitted these, so
    the Execution panel's live subscription had nothing to show for the
    entire duration of a Chat turn, regardless of how long it took."""
    session = orchestrator_service.create_plan("Ship MVP")
    emitted: list[tuple[str, dict[str, Any]]] = []

    def capture_event(event_type: str, *, data: dict[str, Any], **_: Any) -> None:
        emitted.append((event_type, data))

    monkeypatch.setattr("backend.orchestrator.service.emit_event", capture_event)

    result = orchestrator_service.handle_message(session.session_id, "Start execution")

    assert result.status == "completed"
    timeline_events = [(event_type, data) for event_type, data in emitted if event_type.startswith("run.timeline.")]
    # Only the roles the four-stage timeline maps -- architect/devops/
    # responder are intentionally unmapped, matching the "Run plan" pipeline.
    assert [data["stepKey"] for _, data in timeline_events] == ["navigator", "analyzer", "coder", "validator"]
    assert [event_type for event_type, _ in timeline_events] == [
        "run.timeline.analysis",
        "run.timeline.analysis",
        "run.timeline.patch",
        "run.timeline.validation",
    ]
    for event_type, data in timeline_events:
        assert data["actorRole"] == data["stepKey"]
        assert data["status"] == "completed"
        # Real agent output, not an empty/placeholder string.
        assert data["output"]
        matching_result = next(r for r in result.results if r.agent == data["stepKey"])
        assert data["output"] == matching_result.content


@pytest.mark.parametrize(
    ("failing_method", "failure_message"),
    [
        ("append_messages", "message persistence unavailable"),
        ("update_session_artifacts", "artifact persistence unavailable"),
    ],
)
def test_handle_message_completes_only_after_session_persistence(
    orchestrator_service: OrchestratorService,
    monkeypatch: pytest.MonkeyPatch,
    failing_method: str,
    failure_message: str,
) -> None:
    """A session-write failure leaves the run active and suppresses completion."""
    session = orchestrator_service.create_plan("Persist before completion")
    emitted_events: list[str] = []

    def capture_event(event_type: str, **_: Any) -> None:
        """Capture emitted event names without changing orchestration behavior."""
        emitted_events.append(event_type)

    def fail_persistence(*_: Any, **__: Any) -> None:
        """Inject one deterministic durable session-write failure."""
        raise RuntimeError(failure_message)

    monkeypatch.setattr("backend.orchestrator.service.emit_event", capture_event)
    monkeypatch.setattr(orchestrator_service._store, failing_method, fail_persistence)

    with pytest.raises(RuntimeError, match=failure_message):
        orchestrator_service.handle_message(session.session_id, "Start execution")

    persisted_run = orchestrator_service.list_runs(session.session_id)[0]
    assert persisted_run.status == "running"
    # The agent graph itself completes successfully (the injected failure is
    # in post-graph persistence) -- flow.run.started plus one run.timeline.*
    # per mapped agent role (E43-S6: navigator/analyzer/coder/validator;
    # planner/architect/devops/responder aren't part of the four-stage
    # timeline). No completion-status event exists to suppress beyond the
    # run row itself staying "running", asserted above.
    assert emitted_events[0] == "flow.run.started"
    assert all(event.startswith("run.timeline.") for event in emitted_events[1:])
    assert len(emitted_events) == 5


def test_history_persists_across_service_instances(
    orchestrator_service: OrchestratorService,
    tmp_path: Path,
) -> None:
    session = orchestrator_service.create_plan("Track conversation")

    first_run = orchestrator_service.handle_message(session.session_id, "Initial question")
    assert any(entry.role != "user" for entry in first_run.history)

    database_path = tmp_path / "autodev-test.db"
    reloaded_service = OrchestratorService(store=DurableStore(f"sqlite:///{database_path}"))
    second_run = reloaded_service.handle_message(session.session_id, "Follow up")

    assert len(second_run.history) > len(first_run.history)
    assert [entry.role for entry in first_run.history] == [
        entry.role for entry in second_run.history[: len(first_run.history)]
    ]
    assert [entry.content for entry in first_run.history] == [
        entry.content for entry in second_run.history[: len(first_run.history)]
    ]


def test_run_history_is_queryable(orchestrator_service: OrchestratorService) -> None:
    session = orchestrator_service.create_plan("Persist runs")
    orchestrator_service.handle_message(session.session_id, "Run once")
    orchestrator_service.handle_message(session.session_id, "Run twice")

    runs = orchestrator_service.list_runs(session.session_id)

    assert len(runs) == 2
    assert runs[0].trigger_message == "Run twice"
    assert runs[1].trigger_message == "Run once"
    assert runs[0].run_type == "existing_repo_change"
    assert runs[0].current_state == "completed"
    assert runs[0].results
    assert runs[0].steps


def test_run_type_inference_uses_workflow_categories(orchestrator_service: OrchestratorService) -> None:
    session = orchestrator_service.create_plan("Refresh README guidance")

    result = orchestrator_service.handle_message(session.session_id, "Update documentation for operators")

    assert result.run_type == "documentation_update"


def test_agent_contracts_are_exposed(orchestrator_service: OrchestratorService) -> None:
    contracts = orchestrator_service.describe_agent_contracts()

    assert "planner" in contracts
    assert contracts["planner"]["properties"]["steps"]["type"] == "array"
    assert "navigator" in contracts
    assert contracts["navigator"]["properties"]["candidate_files"]["type"] == "array"


class PlannerWithoutMetadata:
    """Planner stub that omits structured step metadata."""

    name = "planner"

    def run(self, _) -> AgentResult:  # pragma: no cover - simple stub
        content = "\n".join(
            [
                "Plan Outline:",
                "- Review requirements",
                "- Define API endpoints.",
                "Review findings with stakeholders",
            ]
        )
        return AgentResult(content=content, metadata={})


class InvalidPlannerFallbackAgent(PlannerAgent):
    """Planner variant with malformed fallback metadata to exercise validation."""

    def fallback_result(self, _) -> AgentResult:  # pragma: no cover - simple stub
        return AgentResult(content="Broken planner output", metadata={"steps": "not-a-list"})


def test_agent_metadata_validation_falls_back_to_contract_valid_payload(
    orchestrator_service: OrchestratorService,
) -> None:
    service = OrchestratorService(
        agents={"planner": InvalidPlannerFallbackAgent()},
        store=cast(DurableStore, orchestrator_service._store),
    )

    session = service.create_plan("Validate metadata")

    assert session.plan == []
    stored_session = service.get_session(session.session_id)
    assert stored_session.plan == session.plan


def test_create_plan_fallback_filters_non_list_lines(orchestrator_service: OrchestratorService) -> None:
    service = OrchestratorService(
        agents={"planner": PlannerWithoutMetadata()},
        store=cast(DurableStore, orchestrator_service._store),
    )

    session = service.create_plan("Fallback parsing")

    assert session.plan == ["Review requirements", "Define API endpoints."]
