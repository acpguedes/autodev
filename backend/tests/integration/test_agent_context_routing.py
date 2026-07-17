from pathlib import Path

from fastapi.testclient import TestClient

from backend.agents.analyzer.agent import AnalyzerAgent
from backend.agents.base import AgentContext
from backend.api.main import app, get_orchestrator
from backend.orchestrator.service import OrchestratorService
from backend.persistence import DurableStore


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _build_orchestrator(tmp_path: Path) -> OrchestratorService:
    _write(tmp_path / "frontend" / "app" / "page.tsx", "export default function Page() { return null; }")
    _write(tmp_path / "backend" / "api" / "main.py", "from fastapi import FastAPI")
    store = DurableStore(f"sqlite:///{tmp_path / 'autodev-test.db'}")
    return OrchestratorService(store=store, project_root=tmp_path)


def test_agent_prompts_receive_goal_and_current_user_request_separately() -> None:
    agent = AnalyzerAgent()
    context = AgentContext(
        session_id="session-1",
        goal="Fortalecer a orquestração multiagente",
        user_request="Aplique apenas mudanças no backend e responda em português",
        history=[{"role": "user", "content": "Aplique apenas mudanças no backend e responda em português"}],
        artifacts={"planner": {"steps": ["Analisar a solicitação"]}},
    )

    prompt_value = agent.prompt.format_prompt(**agent.prepare_inputs(context))
    rendered_messages = prompt_value.to_messages()
    user_prompt = str(rendered_messages[-1].content)

    assert "Goal: Fortalecer a orquestração multiagente" in user_prompt
    assert "Current user request: Aplique apenas mudanças no backend e responda em português" in user_prompt


def test_orchestrator_appends_responder_output_grounded_in_latest_user_request(tmp_path: Path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    session = orchestrator.create_plan("Melhorar a colaboração dos agentes")

    message = "Aplique modificações no backend para manter cada agente no contexto solicitado"
    run = orchestrator.handle_message(session.session_id, message)

    assert run.results[-1].agent == "responder"
    assert run.results[-1].metadata["response_mode"] == "apply_changes"
    assert run.results[-1].metadata["summary"] == message
    assert run.history[-1].role == "responder"
    assert "Solicitação atual" in run.results[-1].content


def test_agent_contracts_endpoint_exposes_responder_schema(tmp_path: Path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    client = TestClient(app)

    response = client.get("/agents/contracts")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert "responder" in payload["contracts"]
