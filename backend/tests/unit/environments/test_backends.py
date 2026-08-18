"""Tests for the Beta isolation backends (E32-S1/S2, ADR-013)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.environments.backends import HardenedContainerBackend, UnavailableBackend
from backend.environments.contracts import (
    EnvironmentBackendError,
    EnvironmentBackendKind,
    EnvironmentProfile,
    NetworkPolicy,
)
from backend.validation.sandbox import SandboxRunner


def test_hardened_container_provisions_a_handle(tmp_path: Path) -> None:
    backend = HardenedContainerBackend()
    handle = backend.provision(
        run_id="run-1", tenant_id="tenant-1", profile=EnvironmentProfile(), workspace_ref=str(tmp_path)
    )
    assert handle.backend_kind is EnvironmentBackendKind.HARDENED_CONTAINER
    assert handle.workspace_path == tmp_path.resolve()
    assert handle.run_id == "run-1"
    assert handle.tenant_id == "tenant-1"


def test_hardened_container_command_sandbox_denies_network_by_default(tmp_path: Path) -> None:
    backend = HardenedContainerBackend()
    handle = backend.provision(
        run_id="run-1", tenant_id="tenant-1", profile=EnvironmentProfile(), workspace_ref=str(tmp_path)
    )
    sandbox = backend.command_sandbox(handle)
    assert isinstance(sandbox, SandboxRunner)


def test_hardened_container_fails_closed_on_unenforceable_network_allowlist(tmp_path: Path) -> None:
    backend = HardenedContainerBackend()
    profile = EnvironmentProfile(network_policy=NetworkPolicy(deny_all=False, allowlist=("pypi.org",)))
    with pytest.raises(EnvironmentBackendError):
        backend.provision(run_id="r", tenant_id="t", profile=profile, workspace_ref=str(tmp_path))


def test_hardened_container_allows_explicit_full_open_profile(tmp_path: Path) -> None:
    backend = HardenedContainerBackend()
    profile = EnvironmentProfile(network_policy=NetworkPolicy(deny_all=False, allowlist=()))
    handle = backend.provision(run_id="r", tenant_id="t", profile=profile, workspace_ref=str(tmp_path))
    assert handle.profile.network_policy.deny_all is False


def test_unavailable_backend_always_denies_provisioning(tmp_path: Path) -> None:
    backend = UnavailableBackend()
    with pytest.raises(EnvironmentBackendError):
        backend.provision(
            run_id="r", tenant_id="t", profile=EnvironmentProfile(), workspace_ref=str(tmp_path)
        )


def test_unavailable_backend_command_sandbox_is_disabled(tmp_path: Path) -> None:
    from backend.environments.contracts import EnvironmentHandle

    backend = UnavailableBackend()
    handle = EnvironmentHandle(
        environment_id="env-1",
        run_id="r",
        tenant_id="t",
        profile=EnvironmentProfile(),
        backend_kind=EnvironmentBackendKind.UNAVAILABLE,
        workspace_path=tmp_path,
    )
    sandbox = backend.command_sandbox(handle)
    assert isinstance(sandbox, SandboxRunner)
