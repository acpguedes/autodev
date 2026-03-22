"""Tests for runtime configuration endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, get_orchestrator, get_repository_intelligence
from backend.config import RuntimeConfigService, get_runtime_config_service
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache
from backend.repository import RepositoryIntelligenceService


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    database_path = tmp_path / "config-test.db"
    config_path = tmp_path / "autodev.config.json"
    repository_root = tmp_path / "workspace"
    repository_root.mkdir(parents=True, exist_ok=True)
    (repository_root / "README.md").write_text("workspace readme")

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(config_path))

    reset_store_cache()
    get_orchestrator.cache_clear()
    get_repository_intelligence.cache_clear()
    get_runtime_config_service.cache_clear()

    app.dependency_overrides[get_runtime_config_service] = lambda: RuntimeConfigService(
        config_path=config_path,
        default_project_root=repository_root,
    )
    app.dependency_overrides[get_orchestrator] = lambda: OrchestratorService(
        store=DurableStore(f"sqlite:///{database_path}"),
        project_root=repository_root,
    )
    app.dependency_overrides[get_repository_intelligence] = lambda: RepositoryIntelligenceService(
        project_root=repository_root,
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    get_orchestrator.cache_clear()
    get_repository_intelligence.cache_clear()
    get_runtime_config_service.cache_clear()
    reset_store_cache()


def test_get_runtime_config_returns_default_document(client: TestClient, tmp_path: Path) -> None:
    response = client.get("/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["llm"]["provider"] == "stub"
    assert payload["config"]["repository"]["project_root"] == str((tmp_path / "workspace").resolve())
    assert payload["instructions"]["config_path"].endswith("autodev.config.json")


def test_update_runtime_config_persists_file_and_updates_repository_context(
    client: TestClient,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "custom-project"
    repository_root.mkdir(parents=True, exist_ok=True)
    (repository_root / "docs").mkdir(parents=True, exist_ok=True)
    (repository_root / "docs" / "README.md").write_text("repository setup guide")

    response = client.put(
        "/config",
        json={
            "config": {
                "version": 1,
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "base_url": "https://example.invalid/v1",
                    "temperature": 0.3,
                    "api_key": "test-key",
                },
                "repository": {
                    "project_root": str(repository_root),
                    "repository_label": "Custom Repo",
                    "default_goal": "Ship configuration center",
                },
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["llm"]["provider"] == "openai"
    assert payload["config"]["repository"]["repository_label"] == "Custom Repo"
    assert (tmp_path / "autodev.config.json").exists()

    saved_document = RuntimeConfigService(
        config_path=tmp_path / "autodev.config.json",
        default_project_root=tmp_path / "workspace",
    ).load_document()
    assert saved_document.config.repository.project_root == str(repository_root.resolve())

    app.dependency_overrides[get_repository_intelligence] = lambda: RepositoryIntelligenceService(
        project_root=Path(payload["config"]["repository"]["project_root"]),
    )
    repository_response = client.get("/repository/context", params={"query": "docs readme", "limit": 5})

    assert repository_response.status_code == 200
    repository_payload = repository_response.json()
    assert repository_payload["root"] == str(repository_root.resolve())
    assert repository_payload["candidate_files"][0]["path"] == "docs/README.md"
