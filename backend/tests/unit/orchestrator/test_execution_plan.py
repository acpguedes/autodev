from pathlib import Path

from fastapi.testclient import TestClient

from backend.agents.base import AgentContext, AgentResult
from backend.api.main import app, get_orchestrator
from backend.events.runtime import get_event_bus, reset_event_bus_for_tests
from backend.execution.modes import ExecutionMode
from backend.orchestrator.service import OrchestratorService, RunStatus
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


def test_execute_plan_performs_real_work_instead_of_simulating_it(
    tmp_path: Path, monkeypatch
) -> None:
    """E14-S1: implementation tasks write a real, observable file (RFC-009)."""
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    orchestrator = _build_orchestrator(tmp_path)
    session = orchestrator.create_plan("Criar plano executável por tarefas")
    orchestrator.handle_message(
        session.session_id, "produza análise e checklist de implementação"
    )

    run = orchestrator.execute_plan(session.session_id)

    note_files = list((tmp_path / ".autodev" / "execution-notes").glob("coding-*.md"))
    assert note_files
    assert any(
        "Expose agent contract schemas" in note.read_text() for note in note_files
    )
    assert all(step.status == "completed" for step in run.steps)


class _FakeCoderAgent:
    """Stands in for CoderAgent, returning real file content (E41-S2 shape)."""

    name = "coder"

    def __init__(self, files: list[dict[str, str]]) -> None:
        self._files = files

    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult(
            content="Coding tasks:\n- backend/payments: Add charge endpoint",
            metadata={
                "coding_tasks": [
                    {"component": "backend/payments", "task": "Add charge endpoint"}
                ],
                "files": self._files,
                "test_updates": [],
                "touched_components": ["backend/payments"],
            },
        )


def test_execute_plan_writes_real_coder_provided_file_content(
    tmp_path: Path, monkeypatch
) -> None:
    """E41-S3: coder-provided real file content is written via the patch engine."""
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    target_path = "backend/payments/charge.py"
    file_content = "def charge():\n    return True\n"
    orchestrator = _build_orchestrator(tmp_path)
    orchestrator._agents["coder"] = _FakeCoderAgent(
        files=[{"path": target_path, "content": file_content}]
    )
    session = orchestrator.create_plan("Criar plano executável por tarefas")
    orchestrator.handle_message(
        session.session_id, "produza análise e checklist de implementação"
    )

    run = orchestrator.execute_plan(session.session_id, mode=ExecutionMode.AUTO)

    written = tmp_path / target_path
    assert written.exists()
    assert written.read_text() == file_content
    assert all(step.status == "completed" for step in run.steps)


def test_execute_plan_publishes_timeline_events_with_captured_output(tmp_path: Path) -> None:
    """E42-S5: executing a plan publishes ``run.timeline.*`` events carrying
    real captured output for every task whose ``source_agent`` maps to a
    timeline stage -- the gap that made both the Chat timeline panel and any
    live-command view (E42-S1) show only two bookend events, never per-task
    progress or output, no matter how the run event stream itself is fixed.
    """
    reset_event_bus_for_tests()
    try:
        orchestrator = _build_orchestrator(tmp_path)
        session = orchestrator.create_plan("Criar plano executável por tarefas")
        orchestrator.handle_message(
            session.session_id, "produza análise e checklist de implementação"
        )

        run = orchestrator.execute_plan(session.session_id)

        published = get_event_bus().replay(run.run_id)
        timeline_events = [e for e in published if e.type.startswith("run.timeline.")]
        assert timeline_events, "expected at least one run.timeline.* event"
        # A validation task's command is always part of the stub plan
        # (asserted by test_orchestrator_builds_execution_plan_from_analysis_
        # artifacts above) and always has a mapped role, so at least one
        # event's output must be non-empty captured command output.
        assert any(event.data.get("output") for event in timeline_events)
        for event in timeline_events:
            assert event.data["stepKey"]
            assert event.data["actorRole"]
            assert event.data["status"] in ("completed", "failed")
            assert event.partitionKey == run.run_id
            assert event.tenantId
    finally:
        reset_event_bus_for_tests()


def test_execute_plan_in_approval_mode_pauses_before_writing_coder_files(
    tmp_path: Path, monkeypatch
) -> None:
    """E41-S3: a real file write pauses for approval like any other action."""
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    target_path = "backend/payments/charge.py"
    orchestrator = _build_orchestrator(tmp_path)
    orchestrator._agents["coder"] = _FakeCoderAgent(
        files=[{"path": target_path, "content": "def charge(): ...\n"}]
    )
    session = orchestrator.create_plan("Criar plano executável por tarefas")
    orchestrator.handle_message(
        session.session_id, "produza análise e checklist de implementação"
    )

    run = orchestrator.execute_plan(session.session_id, mode=ExecutionMode.APPROVAL)

    assert run.status == RunStatus.AWAITING_APPROVAL
    assert not (tmp_path / target_path).exists()
