"""Unit tests for the orchestrator service."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.agents import AgentResult
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache


@pytest.fixture()
def orchestrator_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OrchestratorService:
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


def test_create_plan_fallback_filters_non_list_lines(orchestrator_service: OrchestratorService) -> None:
    service = OrchestratorService(
        agents={"planner": PlannerWithoutMetadata()},
        store=orchestrator_service._store,
    )

    session = service.create_plan("Fallback parsing")

    assert session.plan == ["Review requirements", "Define API endpoints."]
