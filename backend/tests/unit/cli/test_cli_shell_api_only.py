"""Tests for the governed interactive shell (E14-S6).

The static-analysis import check enforces the story's DoD contract
("shell only calls `/v2`") without needing a live server for every test;
the round-trip test proves the happy path against the real FastAPI app via
an in-process ASGI transport (no network, no separate process).
"""

from __future__ import annotations

import ast
import io
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.cli_shell import ShellSession, run_goal

_CLI_SHELL_PATH = Path(__file__).resolve().parents[3] / "cli_shell.py"


def test_cli_shell_never_imports_other_backend_modules() -> None:
    """E14-S6 DoD: the shell only calls `/v2` over HTTP.

    Parses `backend/cli_shell.py`'s own imports (not its transitive
    dependencies -- `httpx` itself obviously imports plenty) and asserts
    none of them reach into another `backend.*` module.
    """
    tree = ast.parse(_CLI_SHELL_PATH.read_text())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                alias.name for alias in node.names if alias.name == "backend" or alias.name.startswith("backend.")
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "backend" or node.module.startswith("backend.")):
                offenders.append(node.module)
    assert offenders == [], f"cli_shell.py must only call /v2 over HTTP; found backend imports: {offenders}"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store, forced onto the stub LLM.

    Mirrors `backend/tests/integration/test_v2_api_contract.py`'s fixture.
    """
    from backend.config.runtime import reset_runtime_config_cache
    from backend.config.settings import reset_settings_cache
    from backend.llm.factory import get_chat_model
    from backend.persistence.database import reset_store_cache

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli-shell.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    get_chat_model.cache_clear()
    from backend.api.main import app

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_store_cache()
    reset_runtime_config_cache()
    get_chat_model.cache_clear()


def test_shell_session_drives_one_goal_to_completion_against_the_real_app(client: TestClient) -> None:
    """Happy path: create a session, execute in auto mode, print a summary.

    `starlette.testclient.TestClient` is a runtime `httpx.Client` subclass
    (over a sync-compatible ASGI transport), so it satisfies `ShellSession`'s
    `.get`/`.post` usage directly at runtime — no separate raw
    `httpx.Client`/`ASGITransport` needed (this httpx version's
    `ASGITransport` is async-only). mypy doesn't always resolve that
    subclass relationship through the installed stubs, hence the ignore
    below; a real `httpx.Client` (as `main()` constructs) needs no such
    workaround.
    """
    session = ShellSession(client, "auto")  # type: ignore[arg-type]
    out = io.StringIO()
    run = run_goal(session, "Criar plano executável por tarefas", out=out, prompt_fn=lambda _prompt: "deny")

    output = out.getvalue()
    assert "session:" in output
    assert "final status:" in output
    assert run["status"] in ("completed", "awaiting_approval")
