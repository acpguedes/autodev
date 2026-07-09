"""Tests for the ``GET /`` service-descriptor front door (E18-S1)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, get_orchestrator, get_repository_intelligence
from backend.config import RuntimeConfigService, get_runtime_config_service
from backend.config.settings import reset_settings_cache
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache
from backend.repository import RepositoryIntelligenceService

_BROWSER_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,*/*;q=0.8"
)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a TestClient with isolated storage, config, and settings caches."""
    database_path = tmp_path / "front-door-test.db"
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


def test_descriptor_json_shape(client: TestClient) -> None:
    """API clients receive the JSON service descriptor with all agreed fields."""
    response = client.get("/", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["name"] == "AutoDev Orchestrator"
    assert body["version"] == "0.3.0"
    assert body["ui_url"] == "http://localhost:3000"
    assert body["docs_url"] == "/docs"
    assert body["health_url"] == "/health"
    assert body["openapi_url"] == "/openapi.json"
    assert body["api"] == {"v2_base": "/v2"}
    assert "description" in body


def test_descriptor_json_for_curl_default_accept(client: TestClient) -> None:
    """``Accept: */*`` (curl default) yields JSON, not HTML."""
    response = client.get("/", headers={"Accept": "*/*"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_browser_accept_yields_html_pointer_page(client: TestClient) -> None:
    """Browser-style Accept headers receive the HTML pointer page with links."""
    response = client.get("/", headers={"Accept": _BROWSER_ACCEPT})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert 'href="http://localhost:3000"' in page
    assert 'href="/docs"' in page
    assert 'href="/health"' in page


def test_html_pointer_page_is_csp_clean(client: TestClient) -> None:
    """The HTML variant carries no script, style, or non-UI external references."""
    response = client.get("/", headers={"Accept": "text/html"})
    page = response.text
    assert "<script" not in page.lower()
    assert "<style" not in page.lower()
    assert "style=" not in page.lower()
    external_refs = re.findall(r"https?://[^\"'\s<>]+", page)
    assert external_refs == ["http://localhost:3000"]
    # Security headers (including the strict CSP) still apply to the page.
    assert "content-security-policy" in response.headers


def test_ui_url_env_override(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``AUTODEV_UI_URL`` overrides the descriptor UI link after a cache reset."""
    monkeypatch.setenv("AUTODEV_UI_URL", "https://autodev.example.com")
    reset_settings_cache()
    body = client.get("/", headers={"Accept": "application/json"}).json()
    assert body["ui_url"] == "https://autodev.example.com"
    html_page = client.get("/", headers={"Accept": "text/html"}).text
    assert 'href="https://autodev.example.com"' in html_page


def test_root_is_public_when_token_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /`` mirrors the ``/health`` auth exemption when a token is set."""
    monkeypatch.setenv("AUTODEV_API_TOKEN", "s3cret")
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/config").status_code == 401


def test_health_regression(client: TestClient) -> None:
    """``/health`` keeps its exact contract next to the new root route."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
