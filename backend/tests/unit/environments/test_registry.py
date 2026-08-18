"""Tests for backend selection by configuration only (E32-S1-T2)."""

from __future__ import annotations

from backend.config.settings import Settings
from backend.environments.backends import HardenedContainerBackend, UnavailableBackend
from backend.environments.contracts import EnvironmentBackendKind
from backend.environments.registry import resolve_backend


def _settings(backend: str) -> Settings:
    return Settings(_env_file=None, autodev_execution_environment_backend=backend)  # type: ignore[call-arg]


def test_unset_configuration_resolves_to_hardened_container_default() -> None:
    kind, backend = resolve_backend(_settings(""))
    assert kind is EnvironmentBackendKind.HARDENED_CONTAINER
    assert isinstance(backend, HardenedContainerBackend)


def test_explicit_hardened_container_resolves_directly() -> None:
    kind, backend = resolve_backend(_settings("hardened_container"))
    assert kind is EnvironmentBackendKind.HARDENED_CONTAINER
    assert isinstance(backend, HardenedContainerBackend)


def test_unrecognized_configuration_fails_closed_to_unavailable() -> None:
    kind, backend = resolve_backend(_settings("bogus-typo"))
    assert kind is EnvironmentBackendKind.UNAVAILABLE
    assert isinstance(backend, UnavailableBackend)


def test_explicit_unavailable_resolves_directly() -> None:
    kind, backend = resolve_backend(_settings("unavailable"))
    assert kind is EnvironmentBackendKind.UNAVAILABLE
    assert isinstance(backend, UnavailableBackend)


def test_configuration_is_case_insensitive() -> None:
    kind, _backend = resolve_backend(_settings("HARDENED_CONTAINER"))
    assert kind is EnvironmentBackendKind.HARDENED_CONTAINER
