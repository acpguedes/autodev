"""Tests for fail-closed network/filesystem policy checks (E32-S2)."""

from __future__ import annotations

from pathlib import Path

from backend.environments.contracts import EnvironmentProfile, FilesystemPolicy, NetworkPolicy
from backend.environments.policy import evaluate_filesystem_access, evaluate_network_provisioning


def test_default_deny_all_network_policy_is_always_provisionable() -> None:
    profile = EnvironmentProfile(network_policy=NetworkPolicy(deny_all=True))
    assert evaluate_network_provisioning(profile) is None


def test_explicit_full_open_network_policy_is_provisionable() -> None:
    profile = EnvironmentProfile(network_policy=NetworkPolicy(deny_all=False, allowlist=()))
    assert evaluate_network_provisioning(profile) is None


def test_unenforceable_allowlist_denies_provisioning() -> None:
    profile = EnvironmentProfile(network_policy=NetworkPolicy(deny_all=False, allowlist=("pypi.org",)))
    denial = evaluate_network_provisioning(profile)
    assert denial is not None
    assert denial.category == "network"
    assert "pypi.org" in denial.target


def test_workspace_relative_path_is_allowed(tmp_path: Path) -> None:
    profile = EnvironmentProfile()
    denial = evaluate_filesystem_access(profile, path="foo/bar.txt", workspace_root=tmp_path)
    assert denial is None


def test_path_traversal_outside_workspace_is_denied(tmp_path: Path) -> None:
    profile = EnvironmentProfile()
    denial = evaluate_filesystem_access(profile, path="../../etc/passwd", workspace_root=tmp_path)
    assert denial is not None
    assert denial.category == "filesystem"


def test_absolute_host_path_outside_workspace_is_denied(tmp_path: Path) -> None:
    profile = EnvironmentProfile()
    denial = evaluate_filesystem_access(profile, path="/etc/passwd", workspace_root=tmp_path)
    assert denial is not None


def test_workspace_only_false_permits_any_path(tmp_path: Path) -> None:
    profile = EnvironmentProfile(filesystem_policy=FilesystemPolicy(workspace_only=False))
    denial = evaluate_filesystem_access(profile, path="/etc/passwd", workspace_root=tmp_path)
    assert denial is None
