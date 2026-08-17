"""Unit tests filling coverage gaps in ``backend/cli.py``.

Complements ``tests/backend/test_cli.py`` (not modified here) by exercising
handlers/branches it does not reach: ``config show`` (both output formats),
``artifacts-cleanup`` (dry-run and real removal), ``sdk new plugin``,
``run message``, ``run execute-plan``, and the ``config validate`` failure
path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest

from backend.cli import main
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Isolate each test in its own database, config file, artifact dir, and cwd."""
    database_path = tmp_path / "cli.db"
    config_path = tmp_path / "autodev.config.json"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "README.md").write_text("CLI workspace")
    artifact_dir = tmp_path / "artifacts"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("AUTODEV_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.delenv("AUTODEV_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    reset_store_cache()
    reset_settings_cache()

    yield

    reset_store_cache()
    reset_settings_cache()


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


def test_config_show_json_format(capsys: pytest.CaptureFixture[str]) -> None:
    """``config show`` (default format) prints the config and instructions as JSON."""
    exit_code = main(["config", "show"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert "config" in payload
    assert "instructions" in payload
    assert "llm" in payload["config"]


def test_config_show_env_format(capsys: pytest.CaptureFixture[str]) -> None:
    """``config show --format env`` prints the raw env-file example, not JSON."""
    exit_code = main(["config", "show", "--format", "env"])

    captured = capsys.readouterr().out
    assert exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured)


# ---------------------------------------------------------------------------
# artifacts-cleanup
# ---------------------------------------------------------------------------


def test_artifacts_cleanup_dry_run_on_empty_store(capsys: pytest.CaptureFixture[str]) -> None:
    """``artifacts-cleanup --dry-run`` reports an empty scan without deleting anything."""
    exit_code = main(["artifacts-cleanup", "--dry-run"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["dry_run"] is True
    assert payload["scanned_count"] == 0
    assert payload["removed"] == []


def test_artifacts_cleanup_real_run_on_empty_store(capsys: pytest.CaptureFixture[str]) -> None:
    """``artifacts-cleanup`` without ``--dry-run`` performs a real (empty) sweep."""
    exit_code = main(["artifacts-cleanup", "--retention-days", "0"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["dry_run"] is False
    assert payload["scanned_count"] == 0


# ---------------------------------------------------------------------------
# sdk new plugin
# ---------------------------------------------------------------------------


def test_sdk_new_plugin_scaffolds_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``sdk new plugin`` scaffolds a project directory and prints its path."""
    output_dir = tmp_path / "my-plugin-project"

    exit_code = main(
        [
            "sdk",
            "new",
            "plugin",
            "acme/hello-plugin",
            "--output",
            str(output_dir),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["path"] == str(output_dir)
    assert (output_dir / "plugin.yaml").exists()
    assert (output_dir / "pyproject.toml").exists()


def test_sdk_new_plugin_invalid_id_raises(tmp_path: Path) -> None:
    """An invalid ``plugin_id`` (not ``namespace/name`` kebab-case) raises ``ValueError``."""
    output_dir = tmp_path / "bad-plugin"

    with pytest.raises(ValueError):
        main(["sdk", "new", "plugin", "NotValidId", "--output", str(output_dir)])


# ---------------------------------------------------------------------------
# run message / run execute-plan
# ---------------------------------------------------------------------------


def test_run_message_executes_agent_cycle(capsys: pytest.CaptureFixture[str]) -> None:
    """``run message`` runs a full agent cycle for an existing session and prints the run."""
    assert main(["plan", "Ship a small CLI improvement"]) == 0
    plan_payload = json.loads(capsys.readouterr().out)
    session_id = plan_payload["session_id"]

    exit_code = main(["run", "message", session_id, "Please proceed with the plan"])

    run_payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert run_payload["session_id"] == session_id


def test_run_message_unknown_session_raises(capsys: pytest.CaptureFixture[str]) -> None:
    """``run message`` against an unknown session id surfaces the orchestrator's ``KeyError``."""
    with pytest.raises(KeyError):
        main(["run", "message", "does-not-exist", "hello"])


def test_run_execute_plan_executes_backlog(capsys: pytest.CaptureFixture[str]) -> None:
    """``run execute-plan`` executes the session's derived plan and prints the run.

    A freshly created session has no ``analyzer`` artifact yet (``plan`` only
    stores the planner's own output), so ``build_execution_plan`` treats it as
    "analysis not run yet" and derives zero tasks. Running the full agent
    graph once via ``run message`` (mirroring ``test_run_message_executes_agent_cycle``)
    populates the session's ``analyzer`` artifact, which is what makes the
    plan steps and analysis follow-ups turn into executable tasks.
    """
    assert main(["plan", "Ship a small CLI improvement"]) == 0
    plan_payload = json.loads(capsys.readouterr().out)
    session_id = plan_payload["session_id"]

    assert main(["run", "message", session_id, "Please proceed with the plan"]) == 0
    capsys.readouterr()

    exit_code = main(["run", "execute-plan", session_id])

    run_payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert run_payload["session_id"] == session_id


# ---------------------------------------------------------------------------
# config validate — failure path
# ---------------------------------------------------------------------------


def test_config_validate_prod_without_required_env_fails(capsys: pytest.CaptureFixture[str]) -> None:
    """``config validate --profile prod`` fails (exit 1) when required prod settings are unset."""
    exit_code = main(["config", "validate", "--profile", "prod"])

    captured = capsys.readouterr()
    assert exit_code == 1
    payload = json.loads(captured.err)
    assert payload["status"] == "error"
    assert "error" in payload


def test_config_validate_restores_env_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed ``config validate`` still restores ``AUTODEV_PROFILE``/``AUTODEV_SETTINGS_FILE``."""
    monkeypatch.delenv("AUTODEV_PROFILE", raising=False)
    monkeypatch.delenv("AUTODEV_SETTINGS_FILE", raising=False)

    import os

    assert main(["config", "validate", "--profile", "prod"]) == 1

    assert "AUTODEV_PROFILE" not in os.environ
    assert "AUTODEV_SETTINGS_FILE" not in os.environ


def test_config_validate_restores_preexisting_env_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A successful ``config validate`` prints settings and restores pre-existing env vars.

    Pre-seeding ``AUTODEV_PROFILE``/``AUTODEV_SETTINGS_FILE`` before the call exercises the
    ``finally`` branch that restores the *previous* value (as opposed to popping it), and
    a valid ``--settings-file`` override exercises the success/print path.
    """
    import os

    settings_file = tmp_path / "override.json"
    settings_file.write_text("{}")
    monkeypatch.setenv("AUTODEV_PROFILE", "local")
    monkeypatch.setenv("AUTODEV_SETTINGS_FILE", str(settings_file))

    exit_code = main(["config", "validate", "--profile", "local", "--settings-file", str(settings_file)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["profile"] == "local"
    assert "database_url" in payload
    assert "llm_provider" in payload
    assert "storage_backend" in payload
    assert os.environ["AUTODEV_PROFILE"] == "local"
    assert os.environ["AUTODEV_SETTINGS_FILE"] == str(settings_file)


# ---------------------------------------------------------------------------
# config set
# ---------------------------------------------------------------------------


def test_config_set_updates_and_persists_fields(capsys: pytest.CaptureFixture[str]) -> None:
    """``config set`` updates the requested LLM/repository fields and persists them."""
    exit_code = main(
        [
            "config",
            "set",
            "--provider",
            "openai",
            "--model",
            "gpt-4o-mini",
            "--base-url",
            "https://api.example.com/v1",
            "--temperature",
            "0.2",
            "--api-key",
            "sk-test-key",
            "--project-root",
            "/tmp/example-project",
            "--repository-label",
            "example-repo",
            "--default-goal",
            "Ship a feature",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    config = payload["config"]
    assert config["llm"]["provider"] == "openai"
    assert config["llm"]["model"] == "gpt-4o-mini"
    assert config["llm"]["base_url"] == "https://api.example.com/v1"
    assert config["llm"]["temperature"] == 0.2
    assert config["repository"]["project_root"] == "/tmp/example-project"
    assert config["repository"]["repository_label"] == "example-repo"
    assert config["repository"]["default_goal"] == "Ship a feature"


def test_config_set_with_no_fields_leaves_config_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    """``config set`` called with no flags is a no-op that still round-trips the config."""
    baseline_exit_code = main(["config", "show"])
    baseline = json.loads(capsys.readouterr().out)["config"]

    exit_code = main(["config", "set"])

    payload = json.loads(capsys.readouterr().out)
    assert baseline_exit_code == 0
    assert exit_code == 0
    assert payload["config"]["llm"] == baseline["llm"]
    assert payload["config"]["repository"] == baseline["repository"]


# ---------------------------------------------------------------------------
# sessions list
# ---------------------------------------------------------------------------


def test_sessions_list_reports_created_sessions(capsys: pytest.CaptureFixture[str]) -> None:
    """``sessions list`` prints every persisted session with its goal and status."""
    assert main(["plan", "Ship a small CLI improvement"]) == 0
    plan_payload = json.loads(capsys.readouterr().out)
    session_id = plan_payload["session_id"]

    exit_code = main(["sessions", "list"])

    sessions = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert isinstance(sessions, list)
    matching = [entry for entry in sessions if entry["session_id"] == session_id]
    assert len(matching) == 1
    assert matching[0]["goal"] == "Ship a small CLI improvement"
    assert "status" in matching[0]
    assert "history_length" in matching[0]


def test_sessions_list_empty_when_no_sessions_created(capsys: pytest.CaptureFixture[str]) -> None:
    """``sessions list`` prints an empty JSON array when no sessions exist yet."""
    exit_code = main(["sessions", "list"])

    sessions = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert sessions == []


# ---------------------------------------------------------------------------
# repository context
# ---------------------------------------------------------------------------


def test_repository_context_returns_ranked_matches(capsys: pytest.CaptureFixture[str]) -> None:
    """``repository context`` ranks files under the project root against the query."""
    exit_code = main(["repository", "context", "--query", "README", "--limit", "5"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert "candidate_files" in payload
    assert "total_files" in payload
    assert payload["total_files"] >= 1


def test_repository_context_clamps_limit_to_valid_range(capsys: pytest.CaptureFixture[str]) -> None:
    """``repository context`` clamps an out-of-range ``--limit`` into ``[1, 25]``."""
    exit_code = main(["repository", "context", "--query", "readme", "--limit", "999"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(payload["candidate_files"]) <= 25


# ---------------------------------------------------------------------------
# quotas get/set (E11-S3)
# ---------------------------------------------------------------------------


def _quotas_set_args(tenant_id: str = "acme-corp", **overrides: str) -> list[str]:
    args = [
        "quotas",
        "set",
        tenant_id,
        "--max-concurrent-runs",
        "5",
        "--max-storage-bytes",
        "1000000",
        "--monthly-token-limit",
        "500000",
        "--monthly-cost-microusd",
        "200000",
        "--requests-per-second",
        "10",
    ]
    for flag, value in overrides.items():
        args.extend([flag, value])
    return args


def test_quotas_set_then_get_round_trips(capsys: pytest.CaptureFixture[str]) -> None:
    """``quotas set`` durably stores a policy that ``quotas get`` then reports."""
    set_exit_code = main(_quotas_set_args("acme-corp", **{"--max-run-tokens": "10000"}))
    set_payload = json.loads(capsys.readouterr().out)
    assert set_exit_code == 0
    assert set_payload["status"] == "ok"
    assert set_payload["policy"]["max_concurrent_runs"] == 5
    assert set_payload["policy"]["default_run_budget"]["max_tokens"] == 10000
    assert set_payload["policy"]["version"] == 1

    get_exit_code = main(["quotas", "get", "acme-corp"])
    get_payload = json.loads(capsys.readouterr().out)
    assert get_exit_code == 0
    assert get_payload["policy"]["max_concurrent_runs"] == 5
    assert get_payload["usage"] == {
        "concurrent_runs": 0,
        "storage_bytes_used": 0,
        "monthly_tokens_used": 0,
        "monthly_cost_microusd_used": 0,
        "month_window_key": get_payload["usage"]["month_window_key"],
    }


def test_quotas_get_without_a_stored_policy_falls_back_to_local_defaults(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``quotas get`` for an unconfigured tenant returns the finite local-mode defaults."""
    exit_code = main(["quotas", "get", "never-configured"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["policy"]["tenant_id"] == "never-configured"
    assert payload["policy"]["max_concurrent_runs"] > 0


def test_quotas_set_rejects_a_stale_expected_version(capsys: pytest.CaptureFixture[str]) -> None:
    """``quotas set`` with a stale ``--expected-version`` fails closed, not silently."""
    main(_quotas_set_args("acme-corp"))
    capsys.readouterr()

    exit_code = main(_quotas_set_args("acme-corp", **{"--expected-version": "99"}))
    err_payload = json.loads(capsys.readouterr().err)
    assert exit_code == 1
    assert err_payload["status"] == "error"
