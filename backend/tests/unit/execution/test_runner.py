"""Tests for the execution runners (E14-S1/S4, ADR-021).

Covers one representative case per action type through the
``InProcessActionRunner``/``CompositeActionRunner`` alias: file writes
reuse the E0 patch engine, command/validation actions reuse the v1
``SandboxRunner`` precursor, and both stay fail-closed by default. Also
covers the three dedicated E14-S4 runners directly: type-rejection
(a runner never silently runs an action outside its scope) and
fail-closed-without-Docker for ``CommandRunner``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.execution.contracts import ExecutionAction, ExecutionActionType
from backend.execution.runner import CommandRunner, InProcessActionRunner, PatchRunner, ValidationRunner
from backend.patches.models import Patch
from backend.validation.sandbox import SandboxPolicy, SandboxRunner


def _sandbox(project_root: Path, **overrides: object) -> SandboxRunner:
    defaults: dict[str, object] = dict(
        enabled=True,
        allow_local=True,
        docker_network="none",
        project_root=project_root,
        timeout_seconds=10,
    )
    defaults.update(overrides)
    return SandboxRunner(policy=SandboxPolicy(**defaults))  # type: ignore[arg-type]


def test_create_file_writes_real_content_when_writes_are_enabled(tmp_path: Path) -> None:
    runner = InProcessActionRunner(project_root=tmp_path, enable_writes=True)
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.CREATE_FILE,
        task_id="task-1",
        step_key="task-1",
        path="notes/task-1.md",
        content="# Task 1\n\nDo the thing.\n",
    )

    result = runner.run(action)

    assert result.status == "succeeded"
    assert result.artifacts == ["notes/task-1.md"]
    assert "+# Task 1" in result.diff
    assert (tmp_path / "notes/task-1.md").read_text() == "# Task 1\n\nDo the thing.\n"


def test_create_file_dry_runs_by_default_and_writes_nothing(tmp_path: Path) -> None:
    runner = InProcessActionRunner(project_root=tmp_path)
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.CREATE_FILE,
        task_id="task-1",
        step_key="task-1",
        path="notes/task-1.md",
        content="content",
    )

    result = runner.run(action)

    assert result.status == "succeeded"
    assert result.artifacts == []
    assert not (tmp_path / "notes/task-1.md").exists()


def test_create_file_rejects_path_traversal(tmp_path: Path) -> None:
    runner = InProcessActionRunner(project_root=tmp_path, enable_writes=True)
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.CREATE_FILE,
        task_id="task-1",
        step_key="task-1",
        path="../outside.md",
        content="leak",
    )

    result = runner.run(action)

    assert result.status == "failed"
    assert "outside" in (result.error or "").lower() or "traversal" in (result.error or "").lower()
    assert not (tmp_path.parent / "outside.md").exists()


def test_apply_patch_delegates_to_the_patch_engine(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("old\n")
    runner = InProcessActionRunner(project_root=tmp_path, enable_writes=True)
    patch = Patch(path="existing.txt", original="old\n", updated="new\n", diff="--- a\n+++ b\n")
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.APPLY_PATCH,
        task_id="task-1",
        step_key="task-1",
        patch=patch,
    )

    result = runner.run(action)

    assert result.status == "succeeded"
    assert (tmp_path / "existing.txt").read_text() == "new\n"


def test_run_command_routes_through_the_sandbox_runner(tmp_path: Path) -> None:
    runner = InProcessActionRunner(
        project_root=tmp_path, sandbox_runner=_sandbox(tmp_path)
    )
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.RUN_COMMAND,
        task_id="task-1",
        step_key="task-1",
        command=["python3", "-c", "print('hi')"],
        cwd=".",
    )

    with patch("shutil.which", return_value=None):
        result = runner.run(action)

    assert result.status == "succeeded"
    assert result.exit_code == 0
    assert "hi" in result.stdout


def test_run_validation_fails_closed_when_sandbox_is_disabled_by_default(
    tmp_path: Path,
) -> None:
    runner = InProcessActionRunner(project_root=tmp_path)
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.RUN_VALIDATION,
        task_id="task-1",
        step_key="task-1",
        command=["pytest"],
        cwd=".",
    )

    result = runner.run(action)

    assert result.status == "succeeded"
    assert result.exit_code == 0
    assert result.artifacts == []


def test_command_runner_fails_closed_without_docker_and_without_local_opt_in(
    tmp_path: Path,
) -> None:
    """E14-S4: CommandRunner never falls back to unsandboxed exec by itself."""
    policy = SandboxPolicy(
        enabled=True, allow_local=False, docker_network="none", project_root=tmp_path, timeout_seconds=5
    )
    runner = CommandRunner(sandbox_runner=SandboxRunner(policy=policy))
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.RUN_COMMAND,
        task_id="task-1",
        step_key="task-1",
        command=["python3", "-c", "print('hi')"],
        cwd=".",
    )

    with patch("shutil.which", return_value=None):
        result = runner.run(action)

    assert result.status == "failed"
    assert result.exit_code == 1


def test_command_runner_rejects_non_command_actions() -> None:
    runner = CommandRunner()
    action = ExecutionAction(
        action_id="a1", type=ExecutionActionType.RUN_VALIDATION, task_id="t1", step_key="t1", command=["pytest"]
    )

    with pytest.raises(ValueError, match="CommandRunner"):
        runner.run(action)


def test_validation_runner_rejects_non_validation_actions() -> None:
    runner = ValidationRunner()
    action = ExecutionAction(
        action_id="a1", type=ExecutionActionType.RUN_COMMAND, task_id="t1", step_key="t1", command=["pytest"]
    )

    with pytest.raises(ValueError, match="ValidationRunner"):
        runner.run(action)


def test_patch_runner_rejects_non_file_or_patch_actions(tmp_path: Path) -> None:
    runner = PatchRunner(project_root=tmp_path)
    action = ExecutionAction(
        action_id="a1", type=ExecutionActionType.RUN_COMMAND, task_id="t1", step_key="t1", command=["pytest"]
    )

    with pytest.raises(ValueError, match="PatchRunner"):
        runner.run(action)


def _environment_manager(tmp_path: Path):
    """Build a real E32 EnvironmentManager for CompositeActionRunner binding tests."""
    from backend.artifacts.pointers import ArtifactPointerStore
    from backend.artifacts.store import LocalArtifactStore
    from backend.config.settings import Settings
    from backend.environments.backends import HardenedContainerBackend
    from backend.environments.contracts import EnvironmentBackendKind
    from backend.environments.manager import EnvironmentManager
    from backend.environments.store import EnvironmentStore
    from backend.persistence.sqlite_adapter import SQLiteStore
    from backend.secret_store.service import SecretService
    from backend.secret_store.store import SecretStore

    store = EnvironmentStore(db_path=tmp_path / "environments.db")
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        storage_backend="local",
        autodev_artifact_dir=str(tmp_path / "artifacts"),
    )
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    pointers = ArtifactPointerStore(store=SQLiteStore(f"sqlite:///{tmp_path / 'pointers.db'}"))
    secret_service = SecretService(
        store=SecretStore(db_path=tmp_path / "secrets.db"), settings=settings
    )
    return EnvironmentManager(
        store=store,
        settings=settings,
        artifact_store=artifact_store,
        artifact_pointers=pointers,
        backend_override=(EnvironmentBackendKind.HARDENED_CONTAINER, HardenedContainerBackend()),
        secret_service=secret_service,
    )


def test_unbound_composite_runner_tags_no_environment(tmp_path: Path) -> None:
    runner = InProcessActionRunner(project_root=tmp_path, enable_writes=True)
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.CREATE_FILE,
        task_id="task-1",
        step_key="task-1",
        path="notes/task-1.md",
        content="content",
    )

    result = runner.run(action)

    assert result.environment == {}


def test_bind_environment_tags_every_result_with_environment_identity(tmp_path: Path) -> None:
    manager = _environment_manager(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))

    runner = InProcessActionRunner(
        project_root=ws, enable_writes=True, environment_manager=manager
    )
    runner.bind_environment(handle)
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.CREATE_FILE,
        task_id="task-1",
        step_key="task-1",
        path="notes/task-1.md",
        content="content",
    )

    result = runner.run(action)

    assert result.environment == {
        "environmentId": handle.environment_id,
        "backendKind": "hardened_container",
        "profileHash": handle.profile.content_hash(),
    }


def test_bind_environment_denies_a_traversal_action_without_dispatching(tmp_path: Path) -> None:
    manager = _environment_manager(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))

    runner = InProcessActionRunner(
        project_root=ws, enable_writes=True, environment_manager=manager
    )
    runner.bind_environment(handle)
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.CREATE_FILE,
        task_id="task-1",
        step_key="task-1",
        path="../../etc/passwd",
        content="pwned",
    )

    result = runner.run(action)

    assert result.status == "failed"
    assert "environment policy denied" in (result.error or "")
    assert not (ws.parent.parent / "etc" / "passwd").exists()


def test_bind_environment_none_reverts_to_unbound_behavior(tmp_path: Path) -> None:
    manager = _environment_manager(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))

    runner = InProcessActionRunner(
        project_root=ws, enable_writes=True, environment_manager=manager
    )
    runner.bind_environment(handle)
    runner.bind_environment(None)
    action = ExecutionAction(
        action_id="a1",
        type=ExecutionActionType.CREATE_FILE,
        task_id="task-1",
        step_key="task-1",
        path="notes/task-1.md",
        content="content",
    )

    result = runner.run(action)

    assert result.environment == {}


def test_bind_environment_without_manager_raises() -> None:
    runner = InProcessActionRunner(project_root=Path("."), enable_writes=True)

    from backend.environments.contracts import (
        EnvironmentBackendKind,
        EnvironmentHandle,
        EnvironmentProfile,
    )

    handle = EnvironmentHandle(
        environment_id="env-1",
        run_id="run-1",
        tenant_id="t1",
        profile=EnvironmentProfile(),
        backend_kind=EnvironmentBackendKind.HARDENED_CONTAINER,
        workspace_path=Path("."),
    )
    with pytest.raises(RuntimeError, match="environment_manager"):
        runner.bind_environment(handle)


def test_bind_environment_injects_resolved_secrets_into_run_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run_command action dispatched under a bound environment sees resolved secrets (E33-S2)."""
    from backend.artifacts.pointers import ArtifactPointerStore
    from backend.artifacts.store import LocalArtifactStore
    from backend.config.settings import Settings, reset_settings_cache
    from backend.environments.backends import HardenedContainerBackend
    from backend.environments.contracts import EnvironmentBackendKind, EnvironmentProfile
    from backend.environments.manager import EnvironmentManager
    from backend.environments.store import EnvironmentStore
    from backend.persistence.sqlite_adapter import SQLiteStore
    from backend.secret_store.contracts import SecretReference
    from backend.secret_store.service import SecretService
    from backend.secret_store.store import SecretStore

    # HardenedContainerBackend.command_sandbox() derives its policy from the
    # process-wide cached Settings singleton, not the manager's own settings
    # -- so the env-driven enable flags must be set for real, not just
    # passed to the manager's Settings instance.
    monkeypatch.setenv("AUTODEV_ENABLE_SANDBOX", "1")
    monkeypatch.setenv("AUTODEV_SANDBOX_ALLOW_LOCAL", "1")
    reset_settings_cache()

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        storage_backend="local",
        autodev_artifact_dir=str(tmp_path / "artifacts"),
        autodev_enable_sandbox=True,
        autodev_sandbox_allow_local=True,
    )
    secret_service = SecretService(
        store=SecretStore(db_path=tmp_path / "secrets.db"), settings=settings
    )
    secret_service.create(
        SecretReference(tenant_id="t1", project="default", name="GIT_TOKEN"),
        "s3cr3t-value",
        actor_id="test",
    )
    manager = EnvironmentManager(
        store=EnvironmentStore(db_path=tmp_path / "environments.db"),
        settings=settings,
        artifact_store=LocalArtifactStore(str(tmp_path / "artifacts")),
        artifact_pointers=ArtifactPointerStore(store=SQLiteStore(f"sqlite:///{tmp_path / 'pointers.db'}")),
        backend_override=(EnvironmentBackendKind.HARDENED_CONTAINER, HardenedContainerBackend()),
        secret_service=secret_service,
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    profile = EnvironmentProfile(env_allowlist=("GIT_TOKEN",))
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws), profile=profile)

    runner = InProcessActionRunner(project_root=ws, environment_manager=manager)
    try:
        with patch("shutil.which", return_value=None):
            runner.bind_environment(handle)
            action = ExecutionAction(
                action_id="a1",
                type=ExecutionActionType.RUN_COMMAND,
                task_id="task-1",
                step_key="task-1",
                command=["python", "-c", "import os; print(os.environ['GIT_TOKEN'])"],
                cwd=".",
            )
            result = runner.run(action)
    finally:
        reset_settings_cache()

    assert result.status == "succeeded", result.error
    assert "s3cr3t-value" in result.stdout
