"""CLI smoke tests for the AutoDev local workflow entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.cli import main
from backend.persistence.database import reset_store_cache


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "cli.db"
    config_path = tmp_path / "autodev.config.json"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "README.md").write_text("CLI workspace")

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(config_path))
    monkeypatch.chdir(tmp_path)
    reset_store_cache()

    yield

    reset_store_cache()


def test_cli_can_update_config_for_ollama(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "config",
            "set",
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--project-root",
            "workspace",
            "--repository-label",
            "CLI Workspace",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["config"]["llm"]["provider"] == "ollama"
    assert payload["config"]["repository"]["repository_label"] == "CLI Workspace"


def test_cli_can_create_plan_and_list_sessions(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["plan", "Ship CLI release slice"]) == 0
    plan_payload = json.loads(capsys.readouterr().out)

    assert plan_payload["session_id"]
    assert plan_payload["status"] == "awaiting_input"

    assert main(["sessions", "list"]) == 0
    sessions_payload = json.loads(capsys.readouterr().out)

    assert len(sessions_payload) == 1
    assert sessions_payload[0]["session_id"] == plan_payload["session_id"]


def test_cli_repository_context_returns_ranked_files(capsys: pytest.CaptureFixture[str]) -> None:
    docs_dir = Path("workspace") / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "README.md").write_text("Context guide")

    exit_code = main(["repository", "context", "--query", "docs readme", "--limit", "3"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["candidate_files"][0]["path"] == "workspace/docs/README.md"
