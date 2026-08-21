"""Tests for the read-only project file tree browser (E43-S4).

Exercises ``GET /v2/repository/tree`` and ``GET /v2/repository/file``
against an isolated ``AUTODEV_PROJECT_ROOT`` fixture directory, mirroring
``backend/tests/unit/api/test_chat_timeline_v2.py``'s TestClient setup.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """A small fixture project tree: one subdirectory, one nested file, one root file."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
    sub = root / "backend"
    sub.mkdir()
    (sub / "app.py").write_text("def handler(): ...\n", encoding="utf-8")
    (root / "logo.bin").write_bytes(b"\xff\xfe\x00\x01binary")
    return root


@pytest.fixture()
def client(tmp_path: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'v2-repository-files.db'}")
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    from backend.api.main import app

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_store_cache()
    reset_runtime_config_cache()


def test_tree_lists_root_children_sorted_directories_first(client: TestClient) -> None:
    response = client.get("/v2/repository/tree")

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "."
    names = [entry["name"] for entry in body["entries"]]
    assert names == ["backend", "logo.bin", "main.py"]
    assert body["entries"][0]["type"] == "directory"
    assert body["entries"][2]["size"] == len("print('hi')\n")


def test_tree_lists_a_subdirectory_by_relative_path(client: TestClient) -> None:
    response = client.get("/v2/repository/tree", params={"path": "backend"})

    assert response.status_code == 200
    body = response.json()
    assert [entry["path"] for entry in body["entries"]] == ["backend/app.py"]


def test_tree_rejects_a_path_traversal_attempt(client: TestClient) -> None:
    response = client.get("/v2/repository/tree", params={"path": "../../etc"})

    assert response.status_code == 400


def test_tree_404s_for_a_nonexistent_directory(client: TestClient) -> None:
    response = client.get("/v2/repository/tree", params={"path": "does-not-exist"})

    assert response.status_code == 404


def test_file_returns_real_text_content(client: TestClient) -> None:
    response = client.get("/v2/repository/file", params={"path": "backend/app.py"})

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "def handler(): ...\n"
    assert body["binary"] is False
    assert body["truncated"] is False


def test_file_flags_binary_content_instead_of_garbling_it(client: TestClient) -> None:
    response = client.get("/v2/repository/file", params={"path": "logo.bin"})

    assert response.status_code == 200
    body = response.json()
    assert body["binary"] is True
    assert body["content"] == ""


def test_file_rejects_a_path_traversal_attempt(client: TestClient) -> None:
    response = client.get("/v2/repository/file", params={"path": "../outside.txt"})

    assert response.status_code == 400


def test_file_404s_for_a_directory_path(client: TestClient) -> None:
    response = client.get("/v2/repository/file", params={"path": "backend"})

    assert response.status_code == 404
