"""Tests for the typed, policy-driven sandbox runner (E11-S4).

All tests must pass WITHOUT docker installed.

Coverage:
- Disabled policy -> skipped=True, no subprocess called.
- Settings truthiness parsing feeds sandbox_policy_from_settings correctly.
- Enabled + no docker + allow_local -> runs locally, captures stdout/stderr/rc.
- Enabled + docker on PATH (mocked) -> routes to docker backend with hardened flags.
- cwd outside the guarded workspace is blocked without spawning a process.
- Command not in allowlist -> blocked/skipped, no subprocess.
- Custom allowlist accepted.
- No docker + allow_local=False fails closed.
- Timeout maps to returncode 124 with a sanitized message.
- ValidationResult fields are populated correctly.
"""

from __future__ import annotations

from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest

from backend.config.settings import Settings
from backend.validation import (
    SandboxPolicy,
    SandboxRunner,
    ValidationJob,
    ValidationResult,
    sandbox_policy_from_settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job(cmd: list[str], job_id: str = "test-job", cwd: str = ".") -> ValidationJob:
    return ValidationJob(job_id=job_id, command=cmd, cwd=cwd)


def _policy(project_root: Path, **overrides: object) -> SandboxPolicy:
    defaults: dict[str, object] = dict(
        enabled=True,
        allow_local=False,
        docker_network="none",
        project_root=project_root,
        timeout_seconds=30,
    )
    defaults.update(overrides)
    return SandboxPolicy(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Settings -> policy conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["0", "false", "False"])
def test_sandbox_false_environment_values_disable_execution(
    raw: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falsy environment strings parse to a disabled policy, not a truthy string."""
    monkeypatch.setenv("AUTODEV_ENABLE_SANDBOX", raw)
    settings = Settings()

    assert sandbox_policy_from_settings(settings).enabled is False


def test_policy_defaults_docker_network_to_none_when_blank() -> None:
    """An unset or blank network setting still defaults the policy to none."""
    settings = Settings(autodev_sandbox_docker_network="")

    assert sandbox_policy_from_settings(settings).docker_network == "none"


# ---------------------------------------------------------------------------
# Disabled policy
# ---------------------------------------------------------------------------


def test_disabled_returns_skipped(tmp_path: Path) -> None:
    runner = SandboxRunner(policy=_policy(tmp_path, enabled=False))
    result = runner.run(_job(["python", "-c", "print(1)"]))

    assert isinstance(result, ValidationResult)
    assert result.skipped is True
    assert result.backend == "disabled"
    assert result.returncode == 0


def test_disabled_does_not_execute(tmp_path: Path) -> None:
    runner = SandboxRunner(policy=_policy(tmp_path, enabled=False))

    with patch("subprocess.run") as mock_run:
        runner.run(_job(["python", "-c", "print(42)"]))
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Enabled — local backend (no docker)
# ---------------------------------------------------------------------------


def test_enabled_local_runs_command(tmp_path: Path) -> None:
    with patch("shutil.which", return_value=None):
        runner = SandboxRunner(
            allowed_commands=["python", "python3"],
            policy=_policy(tmp_path, allow_local=True),
        )
        result = runner.run(_job(["python", "-c", "print(42)"]))

    assert result.skipped is False
    assert result.backend == "local"
    assert result.returncode == 0
    assert "42" in result.stdout


def test_enabled_local_captures_stderr(tmp_path: Path) -> None:
    with patch("shutil.which", return_value=None):
        runner = SandboxRunner(
            allowed_commands=["python", "python3"],
            policy=_policy(tmp_path, allow_local=True),
        )
        result = runner.run(
            _job(["python", "-c", "import sys; sys.stderr.write('err\\n')"])
        )

    assert result.backend == "local"
    assert "err" in result.stderr


def test_enabled_local_nonzero_returncode(tmp_path: Path) -> None:
    with patch("shutil.which", return_value=None):
        runner = SandboxRunner(
            allowed_commands=["python", "python3"],
            policy=_policy(tmp_path, allow_local=True),
        )
        result = runner.run(_job(["python", "-c", "import sys; sys.exit(7)"]))

    assert result.returncode == 7
    assert result.backend == "local"


def test_local_execution_uses_guarded_workspace(tmp_path: Path) -> None:
    """Local execution runs with cwd set to the resolved, guarded workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("shutil.which", return_value=None):
        runner = SandboxRunner(
            allowed_commands=["python", "python3"],
            policy=_policy(tmp_path, allow_local=True),
        )
        result = runner.run(
            _job(
                ["python", "-c", "import os; print(os.getcwd())"],
                cwd="workspace",
            )
        )

    assert result.backend == "local"
    assert result.stdout.strip() == str(workspace.resolve())


# ---------------------------------------------------------------------------
# Enabled — docker backend (mocked — no real docker required)
# ---------------------------------------------------------------------------


def test_enabled_docker_routes_to_docker_backend(tmp_path: Path) -> None:
    fake_completed = MagicMock()
    fake_completed.returncode = 0
    fake_completed.stdout = "mocked\n"
    fake_completed.stderr = ""

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", return_value=fake_completed) as mock_run,
    ):
        runner = SandboxRunner(
            allowed_commands=["python", "python3"], policy=_policy(tmp_path)
        )
        result = runner.run(_job(["python", "-c", "print('hi')"]))

    assert result.backend == "docker"
    assert result.skipped is False
    assert result.stdout == "mocked\n"

    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "docker"
    assert "run" in call_args


def test_docker_command_mounts_only_guarded_workspace(tmp_path: Path) -> None:
    """The docker invocation binds only the resolved workspace, read-only."""
    completed = MagicMock(returncode=0, stdout="", stderr="")
    runner = SandboxRunner(
        allowed_commands=("python",),
        policy=_policy(tmp_path, timeout_seconds=30),
    )

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", return_value=completed) as run,
    ):
        runner.run(
            ValidationJob(
                job_id="mounted",
                command=["python", "-c", "print('ok')"],
                cwd=".",
            )
        )

    command = run.call_args.args[0]
    assert "--network=none" in command
    assert (
        f"type=bind,source={tmp_path.resolve()},target=/workspace,readonly" in command
    )
    assert "--read-only" in command
    assert "--tmpfs=/tmp:rw,noexec,nosuid,size=256m" in command
    assert "--user=65534:65534" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges" in command
    assert "--pids-limit=256" in command
    assert "--memory=512m" in command
    assert "--cpus=1" in command


def test_docker_timeout_returns_124_with_sanitized_message(tmp_path: Path) -> None:
    """A killed container maps to the timeout(1) return code with no leaked args."""
    runner = SandboxRunner(policy=_policy(tmp_path, timeout_seconds=5))

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch(
            "subprocess.run",
            side_effect=TimeoutExpired(cmd=["docker", "run", "--secret=x"], timeout=5),
        ),
    ):
        result = runner.run(_job(["python", "-c", "import time; time.sleep(99)"]))

    assert result.returncode == 124
    assert result.backend == "docker"
    assert "--secret" not in result.stderr
    assert "5s" in result.stderr


# ---------------------------------------------------------------------------
# Workspace guard
# ---------------------------------------------------------------------------


def test_cwd_outside_project_root_is_blocked_without_spawning(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (tmp_path / "outside").mkdir()

    with patch("subprocess.run") as mock_run:
        runner = SandboxRunner(policy=_policy(project_root))
        result = runner.run(_job(["python", "-c", "print(1)"], cwd="../outside"))

    assert result.skipped is True
    assert result.backend == "blocked"
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


def test_command_not_in_allowlist_is_blocked(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        runner = SandboxRunner(allowed_commands=["pytest"], policy=_policy(tmp_path))
        result = runner.run(_job(["rm", "-rf", "/"]))

    assert result.skipped is True
    assert result.backend == "blocked"
    mock_run.assert_not_called()


def test_custom_allowlist_accepted(tmp_path: Path) -> None:
    with patch("shutil.which", return_value=None):
        runner = SandboxRunner(
            allowed_commands=["python", "python3"],
            policy=_policy(tmp_path, allow_local=True),
        )
        result = runner.run(_job(["python", "-c", "print('ok')"]))

    assert result.backend == "local"
    assert result.skipped is False


def test_fails_closed_without_docker_by_default(tmp_path: Path) -> None:
    """With the sandbox enabled but no Docker and no explicit local opt-in,
    the runner must refuse to execute on the host."""
    with patch("shutil.which", return_value=None), patch("subprocess.run") as mock_run:
        runner = SandboxRunner(
            allowed_commands=["python", "python3"],
            policy=_policy(tmp_path, allow_local=False),
        )
        result = runner.run(_job(["python", "-c", "print('nope')"]))

    assert result.skipped is True
    assert result.backend == "unavailable"
    mock_run.assert_not_called()
