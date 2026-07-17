from pathlib import Path

from backend.agents.base import AgentContext
from backend.agents.navigator.agent import NavigatorAgent
from backend.repository import RepositoryIntelligenceService


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_repository_context_ranks_relevant_files(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "project readme")
    _write(tmp_path / "backend" / "api" / "main.py", "from fastapi import FastAPI")
    _write(tmp_path / "backend" / "agents" / "navigator" / "agent.py", "class NavigatorAgent: ...")
    _write(tmp_path / "docs" / "implementation" / "agent_spec.md", "agent api configuration")
    _write(tmp_path / "frontend" / "app" / "page.tsx", "export default function Page() {}")
    _write(tmp_path / "frontend" / "node_modules" / "ignored.js", "ignored")

    service = RepositoryIntelligenceService(project_root=tmp_path)

    context = service.build_context(query="configurar api do agent", limit=5)

    assert context.total_files == 5
    assert "backend" in context.top_directories
    assert any(match.path == "docs/implementation/agent_spec.md" for match in context.candidate_files)
    assert all("node_modules" not in item.path for item in context.candidate_files)
    assert context.matched_terms == ["api", "agent"]


def test_navigator_agent_returns_structured_repository_metadata(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "project readme")
    _write(tmp_path / "backend" / "api" / "main.py", "from fastapi import FastAPI")
    _write(tmp_path / "docs" / "implementation" / "agent_spec.md", "agent api configuration")

    agent = NavigatorAgent(project_root=tmp_path)
    result = agent.run(
        AgentContext(
            session_id="session-1",
            goal="Documentar a API do agent",
            history=[{"role": "user", "content": "falta instrução pra configurar a api do agent"}],
        )
    )

    assert "candidate_files" in result.metadata
    candidate_files = result.metadata["candidate_files"]
    assert candidate_files
    assert candidate_files[0]["path"] in {
        "docs/implementation/agent_spec.md",
        "backend/api/main.py",
    }
    assert result.metadata["total_files"] == 3
