from pathlib import Path

from fastapi.testclient import TestClient

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


def test_orchestrator_builds_execution_plan_from_analysis_artifacts(tmp_path: Path) -> None:
    orchestrator = _build_orchestrator(tmp_path)

    session = orchestrator.create_plan("Separar configuração e executar plano por tarefas")
    orchestrator.handle_message(session.session_id, "analise a mudança e gere tarefas executáveis")

    execution_plan = orchestrator.build_execution_plan(session.session_id)

    assert execution_plan.analysis_summary
    assert execution_plan.tasks
    assert any(task.category == "implementation" for task in execution_plan.tasks)
    assert any(task.category == "validation" for task in execution_plan.tasks)



def test_execution_plan_endpoints_return_tasks_and_execute_them(tmp_path: Path) -> None:
    orchestrator = _build_orchestrator(tmp_path)
    session = orchestrator.create_plan("Criar plano executável por tarefas")
    orchestrator.handle_message(session.session_id, "produza análise e checklist de implementação")

    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    client = TestClient(app)

    plan_response = client.get(f"/sessions/{session.session_id}/execution-plan")
    execute_response = client.post(f"/sessions/{session.session_id}/execution-plan/execute")

    app.dependency_overrides.clear()

    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert plan_payload["analysis_summary"]
    assert len(plan_payload["tasks"]) >= 3

    assert execute_response.status_code == 200
    execute_payload = execute_response.json()
    assert execute_payload["run_type"] == "plan_execution"
    assert len(execute_payload["steps"]) == len(plan_payload["tasks"])
    assert execute_payload["results"]
