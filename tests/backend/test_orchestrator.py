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
