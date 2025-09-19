"""Unit tests for the orchestrator service."""

from backend.agents import AgentResult
from backend.orchestrator.service import OrchestratorService


def test_create_plan_generates_steps() -> None:
    service = OrchestratorService()
    session = service.create_plan("Implement orchestrator")

    assert session.session_id
    assert session.plan
    assert "Implement" in session.plan[0]


def test_handle_message_returns_agent_responses() -> None:
    service = OrchestratorService()
    session = service.create_plan("Ship MVP")

    result = service.handle_message(session.session_id, "Start execution")

    assert result.session_id == session.session_id
    agent_names = [execution.agent for execution in result.results]
    assert "navigator" in agent_names
    assert any("DevOps" in execution.content for execution in result.results)
    assert result.history[0].role == "user"
    assert result.history[0].content == "Start execution"
    assert all(entry.content for entry in result.history)


def test_history_persists_across_messages() -> None:
    service = OrchestratorService()
    session = service.create_plan("Track conversation")

    first_run = service.handle_message(session.session_id, "Initial question")
    assert any(entry.role != "user" for entry in first_run.history)

    second_run = service.handle_message(session.session_id, "Follow up")

    assert len(second_run.history) > len(first_run.history)
    assert [entry.role for entry in first_run.history] == [
        entry.role for entry in second_run.history[: len(first_run.history)]
    ]
    assert [entry.content for entry in first_run.history] == [
        entry.content for entry in second_run.history[: len(first_run.history)]
    ]


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


def test_create_plan_fallback_filters_non_list_lines() -> None:
    service = OrchestratorService(agents={"planner": PlannerWithoutMetadata()})

    session = service.create_plan("Fallback parsing")

    assert session.plan == ["Review requirements", "Define API endpoints."]
