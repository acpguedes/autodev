"""Tests for the execution-environment abstraction contracts (E32-S1)."""

from __future__ import annotations

from backend.environments.contracts import (
    EnvironmentBackendKind,
    EnvironmentProfile,
    FilesystemPolicy,
    NetworkPolicy,
)


def test_environment_backend_kind_values() -> None:
    assert {member.value for member in EnvironmentBackendKind} == {
        "hardened_container",
        "unavailable",
    }


def test_default_profile_is_deny_all_and_workspace_only() -> None:
    profile = EnvironmentProfile()
    assert profile.network_policy == NetworkPolicy(deny_all=True, allowlist=())
    assert profile.filesystem_policy == FilesystemPolicy(workspace_only=True, read_only_base=True)


def test_content_hash_is_stable_for_identical_profiles() -> None:
    a = EnvironmentProfile(profile_id="p1", base_image="python:3.11-slim")
    b = EnvironmentProfile(profile_id="p1", base_image="python:3.11-slim")
    assert a.content_hash() == b.content_hash()


def test_content_hash_changes_with_profile_fields() -> None:
    a = EnvironmentProfile(profile_id="p1")
    b = EnvironmentProfile(profile_id="p2")
    assert a.content_hash() != b.content_hash()


def test_content_hash_changes_with_network_policy() -> None:
    a = EnvironmentProfile()
    b = EnvironmentProfile(network_policy=NetworkPolicy(deny_all=False, allowlist=("pypi.org",)))
    assert a.content_hash() != b.content_hash()
