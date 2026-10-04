"""E62-S3: two sessions bound to different projects resolve different roots in one process."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache
from backend.projects import ProjectStore, resolve_project_root


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, Path, Path], None, None]:
    root_a, root_b = tmp_path / "proj-a", tmp_path / "proj-b"
    for root, name in ((root_a, "a.txt"), (root_b, "b.txt")):
        root.mkdir()
        (root / name).write_text(f"secret-{name}", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'per-session.db'}")
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    from backend.api.main import app

    with TestClient(app) as client:
        yield client, root_a, root_b
    app.dependency_overrides.clear()
    reset_store_cache()
    reset_runtime_config_cache()


def _session(client: TestClient, project_id: str) -> str:
    response = client.post("/v2/sessions", json={"goal": "g", "project_id": project_id})
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def test_sessions_resolve_different_roots_and_cannot_cross(env) -> None:
    client, root_a, root_b = env
    store = ProjectStore()
    pa = store.create(tenant_id="default", name="a", root_path=root_a)
    pb = store.create(tenant_id="default", name="b", root_path=root_b)
    sa, sb = _session(client, pa.project_id), _session(client, pb.project_id)

    assert resolve_project_root(session_id=sa) == root_a.resolve()
    assert resolve_project_root(session_id=sb) == root_b.resolve()

    own = client.get("/v2/repository/file", params={"path": "a.txt", "session_id": sa})
    assert own.status_code == 200 and "secret-a.txt" in own.text
    assert client.get("/v2/repository/file", params={"path": "b.txt", "session_id": sa}).status_code == 404
    traversal = client.get("/v2/repository/file", params={"path": "../proj-b/b.txt", "session_id": sa})
    assert traversal.status_code == 400
    assert client.get("/v2/repository/file", params={"path": "b.txt", "session_id": sb}).status_code == 200
    # /repository/symbols guard uses the same per-session root
    assert client.get("/repository/symbols", params={"path": "../proj-b/b.txt", "session_id": sa}).status_code == 403


def test_request_without_session_falls_back_to_active_project_then_process_root(env, tmp_path: Path) -> None:
    client, root_a, _ = env
    assert resolve_project_root() == tmp_path.resolve()  # no project at all -> process-wide root
    ProjectStore().create(tenant_id="default", name="a", root_path=root_a, activate=True)
    assert resolve_project_root() == root_a.resolve()
    assert client.get("/v2/repository/file", params={"path": "a.txt"}).status_code == 200


def test_unknown_project_id_is_rejected(env) -> None:
    client, _, _ = env
    response = client.post("/v2/sessions", json={"goal": "g", "project_id": "nope"})
    assert response.status_code == 404
