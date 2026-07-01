"""Tests for optional bearer-token auth and API-key redaction."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, get_orchestrator, get_repository_intelligence
from backend.config import RuntimeConfigService, get_runtime_config_service
from backend.config.runtime import API_KEY_REDACTION
from backend.config.settings import reset_settings_cache
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache
from backend.repository import RepositoryIntelligenceService


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    database_path = tmp_path / "sec-test.db"
    config_path = tmp_path / "autodev.config.json"
    repository_root = tmp_path / "workspace"
    repository_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(repository_root))

    reset_store_cache()
    reset_settings_cache()
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
    reset_settings_cache()


def test_no_token_configured_allows_requests(client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_API_TOKEN", raising=False)
    assert client.get("/health").status_code == 200
    assert client.get("/config").status_code == 200


def test_token_configured_rejects_missing_header(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_API_TOKEN", "s3cret")
    # Health check stays public even with auth enabled.
    assert client.get("/health").status_code == 200
    # Protected endpoint requires the token.
    assert client.get("/config").status_code == 401


def test_token_configured_accepts_valid_bearer(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_API_TOKEN", "s3cret")
    resp = client.get("/config", headers={"Authorization": "Bearer s3cret"})
    assert resp.status_code == 200


def test_token_configured_rejects_wrong_token(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_API_TOKEN", "s3cret")
    resp = client.get("/config", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_config_endpoint_redacts_api_key(client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_API_TOKEN", raising=False)
    client.put(
        "/config",
        json={
            "config": {
                "version": 1,
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "base_url": "",
                    "temperature": 0.2,
                    "api_key": "sk-super-secret",
                },
                "repository": {"project_root": ".", "repository_label": "r", "default_goal": "g"},
            }
        },
    )

    payload = client.get("/config").json()
    assert payload["config"]["llm"]["api_key"] == API_KEY_REDACTION
    assert "sk-super-secret" not in payload["instructions"]["env_file_example"]


def test_put_with_redaction_placeholder_preserves_stored_key(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("AUTODEV_API_TOKEN", raising=False)
    base = {
        "version": 1,
        "llm": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "base_url": "",
            "temperature": 0.2,
            "api_key": "sk-real-key",
        },
        "repository": {"project_root": ".", "repository_label": "r", "default_goal": "g"},
    }
    client.put("/config", json={"config": base})

    # Client echoes the redaction placeholder back; the stored key must survive.
    echoed = {**base, "llm": {**base["llm"], "api_key": API_KEY_REDACTION}}
    client.put("/config", json={"config": echoed})

    service = RuntimeConfigService(
        config_path=tmp_path / "autodev.config.json",
        default_project_root=tmp_path / "workspace",
    )
    assert service.load().llm.api_key == "sk-real-key"
