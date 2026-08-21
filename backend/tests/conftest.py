"""Shared fixtures for the ``backend/tests`` pyramid (unit + integration).

These fixtures exist to keep the backend test suite deterministic and
local-first: no live network access, no live database/queue, and no
wall-clock or RNG flakiness. Prefer them over ad hoc mocks when writing new
tests so behavior stays reproducible across runs and machines.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.agents.provider import ScriptedLLMProvider, StubEmbeddingProvider, StubLLMProvider
from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.llm.composition import reset_model_composition_cache
from backend.llm.factory import get_chat_model

#: Fixed seed used to make any randomized test behavior reproducible.
DETERMINISTIC_SEED = 1337

#: Environment variables that can carry real provider credentials or endpoints
#: into a test run. Cleared for every test by :func:`isolated_runtime_config`.
_CREDENTIAL_ENV_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "OLLAMA_BASE_URL",
    "LLM_MODEL",
)


@pytest.fixture(autouse=True)
def isolated_runtime_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Isolate every test from the developer's real runtime configuration.

    :class:`~backend.config.runtime.RuntimeConfigService` resolves its config
    path from ``AUTODEV_CONFIG_PATH``, falling back to
    ``<AUTODEV_PROJECT_ROOT or cwd>/autodev.config.json``. Since the suite runs
    from the repository root, an unisolated test reads the developer's own
    ``autodev.config.json`` — which may hold a real provider, base URL and API
    key. That file is gitignored, so the exposure is per-machine and invisible
    in CI.

    This became load-bearing when :class:`~backend.flows.handlers.AgentNodeHandler`
    started composing a gateway-carrying runtime by default: without this
    fixture, any test exercising an agent would issue a live, credentialed model
    call against whatever endpoint the developer had configured.

    The fixture points the config path at a per-test file, forces the offline
    ``stub`` provider, strips credential-bearing variables, and resets every
    cache that snapshots them.

    The reset runs on entry only, deliberately. Isolation is already complete:
    the next test's own setup resets the same caches before it can observe
    anything. A teardown reset would additionally be unsafe — this fixture
    requests ``monkeypatch``, so it finalizes *before* monkeypatch unwinds, and
    a test that patched one of the cached factories (as
    ``unit/persistence/test_backup.py`` patches ``get_settings``) would still
    have its patch installed, leaving the reset helper to call ``cache_clear``
    on a plain function.

    Tests that need a specific configuration still win: their own
    ``monkeypatch`` calls run after this fixture and override it.

    Args:
        tmp_path: Pytest's per-test temporary directory.
        monkeypatch: Pytest's environment patcher, scoped to the test.

    Yields:
        ``None``. The isolation is ambient for the duration of the test.
    """
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "autodev.config.json"))
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    for variable in _CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)

    reset_runtime_config_cache()
    reset_settings_cache()
    reset_model_composition_cache()
    get_chat_model.cache_clear()
    yield


@pytest.fixture(autouse=True)
def deterministic_rng() -> Iterator[random.Random]:
    """Seed the stdlib RNG for every test and yield a private ``Random`` too.

    Autouse so accidental use of the module-level :mod:`random` functions
    (``random.random()``, ``random.choice()``, ...) inside test code or the
    code under test stays reproducible. Tests that want an isolated
    generator (rather than the shared module-level one) can depend on the
    fixture value directly instead.

    Yields:
        A :class:`random.Random` instance seeded with
        :data:`DETERMINISTIC_SEED`, independent of the module-level state.
    """
    random.seed(DETERMINISTIC_SEED)
    yield random.Random(DETERMINISTIC_SEED)


@dataclass
class ControllableClock:
    """A manually advanceable clock for deterministic time-dependent tests.

    Matches the ``Callable[[], float]`` monotonic-clock injection point used
    across the codebase (see ``backend.flows.engine``, ``backend.routing``,
    etc.) as well as ``Callable[[], datetime]`` wall-clock injection points
    (see ``backend.flows.human``) via :meth:`now`.

    Attributes:
        _monotonic: Current monotonic seconds value returned by ``__call__``.
        _wall_clock: Current wall-clock timestamp returned by :meth:`now`.
    """

    _monotonic: float = 0.0
    _wall_clock: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    def __call__(self) -> float:
        """Return the current monotonic seconds value.

        Returns:
            The clock's current monotonic value, in seconds.
        """
        return self._monotonic

    def now(self) -> datetime:
        """Return the current wall-clock timestamp.

        Returns:
            The clock's current timezone-aware :class:`datetime`.
        """
        return self._wall_clock

    def advance(self, seconds: float) -> None:
        """Advance both the monotonic and wall-clock readings.

        Args:
            seconds: Number of seconds to move the clock forward by.
        """
        self._monotonic += seconds
        self._wall_clock += timedelta(seconds=seconds)


@pytest.fixture
def controllable_clock() -> ControllableClock:
    """Provide a fresh, manually advanceable clock for a single test.

    Returns:
        A new :class:`ControllableClock` starting at ``t=0`` /
        ``2026-01-01T00:00:00Z``.
    """
    return ControllableClock()


@pytest.fixture
def stub_llm_provider() -> StubLLMProvider:
    """Provide the canonical fixed-response offline LLM provider.

    Returns:
        A :class:`~backend.agents.provider.StubLLMProvider` returning a
        constant completion for every call.
    """
    return StubLLMProvider()


@pytest.fixture
def scripted_llm_provider_factory() -> Callable[..., ScriptedLLMProvider]:
    """Provide a factory for scripted, multi-turn offline LLM providers.

    Returns:
        A callable with the same signature as
        :class:`~backend.agents.provider.ScriptedLLMProvider`, so tests can
        build one or more scripted providers with different scripts.
    """
    return ScriptedLLMProvider


@pytest.fixture
def stub_embedding_provider() -> StubEmbeddingProvider:
    """Provide the canonical deterministic offline embedding provider.

    Returns:
        A :class:`~backend.repository.embeddings.provider.StubEmbeddingProvider`
        (re-exported from :mod:`backend.agents.provider`) producing
        deterministic, dependency-free embeddings.
    """
    return StubEmbeddingProvider()


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Provide a fresh, empty temporary directory scoped to the test.

    Thin wrapper over pytest's built-in ``tmp_path`` fixture kept for
    naming symmetry with the other fixtures in this module; use it when a
    test needs an explicit "workspace root" name for readability.

    Args:
        tmp_path: Pytest's per-test temporary directory fixture.

    Returns:
        The same temporary directory path.
    """
    return tmp_path
