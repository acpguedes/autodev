"""Tests for U14 sandbox runner (backend/validation/).

All tests must pass WITHOUT docker installed.

Coverage:
- Disabled (no env var) → skipped=True, no subprocess called.
- Enabled + no docker → runs locally, captures stdout.
- Enabled + docker on PATH (mocked) → routes to docker backend.
- Command not in allowlist → blocked/skipped, no subprocess.
- Custom allowlist accepted.
- ValidationResult fields are populated correctly.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from backend.validation import SandboxRunner, ValidationJob, ValidationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job(cmd: list[str], job_id: str = "test-job") -> ValidationJob:
    return ValidationJob(job_id=job_id, command=cmd)


# ---------------------------------------------------------------------------
# Disabled (default — env var absent)
# ---------------------------------------------------------------------------


def test_disabled_returns_skipped(monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_ENABLE_SANDBOX", raising=False)
    runner = SandboxRunner()
    result = runner.run(_job(["python", "-c", "print(1)"]))

    assert isinstance(result, ValidationResult)
    assert result.skipped is True
    assert result.backend == "disabled"
    assert result.returncode == 0


def test_disabled_does_not_execute(monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_ENABLE_SANDBOX", raising=False)
    runner = SandboxRunner()

    with patch("subprocess.run") as mock_run:
        runner.run(_job(["python", "-c", "print(42)"]))
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Enabled — local backend (no docker)
# ---------------------------------------------------------------------------


def test_enabled_local_runs_command(monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_SANDBOX", "1")

    # Ensure docker is NOT available so we fall through to local.
    with patch("shutil.which", return_value=None):
        runner = SandboxRunner(allowed_commands=["python", "python3"])
        result = runner.run(_job(["python", "-c", "print(42)"]))

    assert result.skipped is False
    assert result.backend == "local"
    assert result.returncode == 0
    assert "42" in result.stdout


def test_enabled_local_captures_stderr(monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_SANDBOX", "1")

    with patch("shutil.which", return_value=None):
        runner = SandboxRunner(allowed_commands=["python", "python3"])
        result = runner.run(
            _job(["python", "-c", "import sys; sys.stderr.write('err\n')"])
        )

    assert result.backend == "local"
    assert "err" in result.stderr


def test_enabled_local_nonzero_returncode(monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_SANDBOX", "1")

    with patch("shutil.which", return_value=None):
        runner = SandboxRunner(allowed_commands=["python", "python3"])
        result = runner.run(
            _job(["python", "-c", "import sys; sys.exit(7)"])
        )

    assert result.returncode == 7
    assert result.backend == "local"


# ---------------------------------------------------------------------------
# Enabled — docker backend (mocked — no real docker required)
# ---------------------------------------------------------------------------


def test_enabled_docker_routes_to_docker_backend(monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_SANDBOX", "1")

    fake_completed = MagicMock()
    fake_completed.returncode = 0
    fake_completed.stdout = "mocked\n"
    fake_completed.stderr = ""

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", return_value=fake_completed) as mock_run,
    ):
        runner = SandboxRunner(allowed_commands=["python", "python3"])
        result = runner.run(_job(["python", "-c", "print('hi')"]))

    assert result.backend == "docker"
    assert result.skipped is False
    assert result.stdout == "mocked\n"

    # Verify docker was invoked as the command.
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "docker"
    assert "run" in call_args


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


def test_command_not_in_allowlist_is_blocked(monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_SANDBOX", "1")

    with patch("subprocess.run") as mock_run:
        runner = SandboxRunner(allowed_commands=["pytest"])
        result = runner.run(_job(["rm", "-rf", "/"]))

    assert result.skipped is True
    assert result.backend == "blocked"
    mock_run.assert_not_called()


def test_custom_allowlist_accepted(monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_SANDBOX", "1")

    with patch("shutil.which", return_value=None):
        runner = SandboxRunner(allowed_commands=["python", "python3"])
        result = runner.run(_job(["python", "-c", "print('ok')"]))

    assert result.backend == "local"
    assert result.skipped is False
