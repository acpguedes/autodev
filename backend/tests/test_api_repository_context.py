from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.main import app, get_repository_intelligence
from backend.repository import RepositoryIntelligenceService


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_repository_context_endpoint_returns_ranked_matches(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "project readme")
    _write(tmp_path / "backend" / "api" / "main.py", "from fastapi import FastAPI")
    _write(tmp_path / "docs" / "implementation" / "agent_spec.md", "agent api configuration")

    app.dependency_overrides[get_repository_intelligence] = lambda: RepositoryIntelligenceService(project_root=tmp_path)
    client = TestClient(app)

    response = client.get("/repository/context", params={"query": "agent api", "limit": 2})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 3
    assert payload["candidate_files"]
    assert payload["candidate_files"][0]["path"] in {
        "docs/implementation/agent_spec.md",
        "backend/api/main.py",
    }
    assert payload["matched_terms"] == ["agent", "api"]
