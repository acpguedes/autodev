"""Real-Docker security contract for the E11-S4 hardened sandbox.

These tests require a working Docker daemon and pull ``python:3.11-slim``.
They are skipped (not xfailed) when Docker is unavailable so local
development without Docker stays green; CI installs Docker and must report
these as passed, not skipped (see ``.github/workflows/ci-backend.yml``).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend.validation import SandboxRunner, ValidationJob, sandbox_policy_from_settings
from backend.validation.sandbox import SandboxPolicy


def _docker_runner(project_root: Path) -> SandboxRunner:
    """Build a runner with a real, hardened policy rooted at ``project_root``."""
    base = sandbox_policy_from_settings()
    policy = SandboxPolicy(
        enabled=True,
        allow_local=base.allow_local,
        docker_network="none",
        project_root=project_root.resolve(),
        timeout_seconds=60,
    )
    return SandboxRunner(allowed_commands=("python",), policy=policy)


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker is required for the sandbox security contract",
)
def test_docker_sandbox_denies_network_by_default(tmp_path: Path) -> None:
    """The default `--network=none` container cannot reach the network."""
    runner = _docker_runner(tmp_path)
    result = runner.run(
        ValidationJob(
            job_id="network-denied",
            command=[
                "python",
                "-c",
                (
                    "import socket; "
                    "socket.create_connection(('1.1.1.1', 53), timeout=1)"
                ),
            ],
            cwd=".",
        )
    )

    assert result.backend == "docker"
    assert result.returncode != 0


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker is required for the sandbox security contract",
)
def test_docker_sandbox_exposes_workspace_but_not_host_sibling(
    tmp_path: Path,
) -> None:
    """Only the guarded workspace is bind-mounted, never its host siblings."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "visible.txt").write_text("visible", encoding="utf-8")
    (tmp_path / "host-only.txt").write_text("hidden", encoding="utf-8")
    runner = _docker_runner(workspace)

    result = runner.run(
        ValidationJob(
            job_id="filesystem",
            command=[
                "python",
                "-c",
                (
                    "from pathlib import Path; "
                    "assert Path('/workspace/visible.txt').read_text() == 'visible'; "
                    "assert not Path('/host-only.txt').exists()"
                ),
            ],
            cwd=".",
        )
    )

    assert result.returncode == 0


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker is required for the sandbox security contract",
)
def test_docker_sandbox_cannot_escalate_to_root(tmp_path: Path) -> None:
    """The container runs as an unprivileged uid and cannot escalate to root."""
    runner = _docker_runner(tmp_path)
    result = runner.run(
        ValidationJob(
            job_id="privilege",
            command=[
                "python",
                "-c",
                (
                    "import os; assert os.geteuid() == 65534; "
                    "\ntry:\n os.setuid(0)\nexcept PermissionError:\n pass"
                    "\nelse:\n raise SystemExit(9)"
                ),
            ],
            cwd=".",
        )
    )

    assert result.returncode == 0
