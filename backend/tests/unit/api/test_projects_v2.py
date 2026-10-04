"""E62-S4: ``/v2/projects`` API."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'projects-v2.db'}")
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    from backend.api.main import app

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    reset_store_cache()
    reset_runtime_config_cache()


def test_three_paths_and_listing(client: TestClient, tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("x")
    assert client.get("/v2/projects").json()["items"] == []

    init = client.post("/v2/projects/init", json={"root": str(existing)})
    assert init.status_code == 201 and init.json()["active"] is True
    assert (existing / "keep.txt").read_text() == "x"

    created = client.post("/v2/projects/create", json={"root": str(tmp_path / "brand-new"), "name": "bn"})
    assert created.status_code == 201 and created.json()["name"] == "bn"

    opened = client.post("/v2/projects/open", json={"root": str(existing)})
    assert opened.status_code == 200 and opened.json()["projectId"] == init.json()["projectId"]

    listing = client.get("/v2/projects").json()
    assert len(listing["items"]) == 2
    assert listing["activeProjectId"] == init.json()["projectId"]

    other = created.json()["projectId"]
    assert client.post(f"/v2/projects/{other}/activate").json()["active"] is True
    assert client.post("/v2/projects/nope/activate").status_code == 404


def test_error_mapping(client: TestClient, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert client.post("/v2/projects/open", json={"root": str(plain)}).status_code == 400
    assert client.post("/v2/projects/create", json={"root": str(plain)}).status_code == 400
    (plain / ".autodev").mkdir()
    (plain / ".autodev" / "config.json").write_text("[]")
    assert client.post("/v2/projects/open", json={"root": str(plain)}).status_code == 422
