"""Tests for the self-hosted, CSP-compliant ``/docs`` page (E18-S2)."""

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

_STATIC_ASSETS = {
    "/static/swagger/swagger-ui-bundle.js": "javascript",
    "/static/swagger/swagger-ui-init.js": "javascript",
    "/static/swagger/swagger-ui.css": "text/css",
    "/static/swagger/favicon-32x32.png": "image/png",
}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a TestClient with isolated storage, config, and settings caches."""
    database_path = tmp_path / "docs-test.db"
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


def test_docs_page_renders_html(client: TestClient) -> None:
    """``/docs`` serves the self-hosted Swagger UI shell."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="swagger-ui"' in response.text


def test_docs_page_references_are_same_origin_only(client: TestClient) -> None:
    """Every ``src``/``href`` in the docs HTML is a same-origin absolute path."""
    page = client.get("/docs").text
    references = re.findall(r'(?:src|href)="([^"]+)"', page)
    assert references, "expected asset references in the /docs page"
    for reference in references:
        assert reference.startswith("/"), f"non-same-origin reference: {reference}"


def test_docs_page_has_no_inline_script(client: TestClient) -> None:
    """All ``<script>`` tags load external same-origin files with empty bodies."""
    page = client.get("/docs").text
    scripts = re.findall(r"<script([^>]*)>(.*?)</script>", page, flags=re.DOTALL)
    assert scripts, "expected script tags in the /docs page"
    for attributes, body in scripts:
        assert 'src="/' in attributes
        assert body.strip() == ""


def test_docs_page_does_not_use_cdn(client: TestClient) -> None:
    """Regression: the jsdelivr CDN must never reappear in the docs page."""
    page = client.get("/docs").text
    assert "cdn.jsdelivr.net" not in page
    assert "http://" not in page and "https://" not in page


def test_static_swagger_assets_served_with_content_types(client: TestClient) -> None:
    """Each vendored asset is served same-origin with a sane content type."""
    for path, expected_type in _STATIC_ASSETS.items():
        response = client.get(path)
        assert response.status_code == 200, path
        assert expected_type in response.headers["content-type"], path


def test_docs_response_keeps_security_headers(client: TestClient) -> None:
    """The strict security headers still apply to the docs page."""
    response = client.get("/docs")
    csp = response.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert response.headers.get("x-frame-options") == "DENY"


def test_redoc_is_disabled(client: TestClient) -> None:
    """``/redoc`` is intentionally gone — one vendored doc UI is enough."""
    assert client.get("/redoc").status_code == 404


def test_openapi_schema_still_served(client: TestClient) -> None:
    """``/openapi.json`` keeps working for the docs page and API clients."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["version"] == "0.3.0"


def test_static_assets_public_when_token_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mounted static files bypass the app-level token gate (load-bearing).

    ``/docs`` is a public path, so the assets it loads must stay reachable
    without a token; Starlette mounts do not inherit FastAPI app dependencies.
    A future move to middleware-based auth would break this — this test pins
    the contract.
    """
    monkeypatch.setenv("AUTODEV_API_TOKEN", "s3cret")
    assert client.get("/docs").status_code == 200
    for path in _STATIC_ASSETS:
        assert client.get(path).status_code == 200, path
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/config").status_code == 401
