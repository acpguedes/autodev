"""Unit tests for backend/reasoning/registry.py (E4-S1).

Covers :class:`ReasoningStrategyRegistry`'s register/get/resolve/versions/
list_ids/unregister methods, plus the module-level ``is_host_compatible``
helper, using a minimal duck-typed fake strategy (the contract's
``ReasoningStrategy`` is a ``Protocol`` with no runtime-checkable base).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from backend.reasoning.contract import ReasoningContext, ReasoningInput, ReasoningOutput
from backend.reasoning.registry import PLATFORM_HOST_VERSION, ReasoningStrategyRegistry, is_host_compatible


@dataclass
class _FakeStrategy:
    """Minimal duck-typed stand-in for the ``ReasoningStrategy`` protocol.

    Not frozen (and defines ``run``) so it structurally satisfies the
    ``ReasoningStrategy`` Protocol, whose ``id``/``version``/``host_api``
    attributes are expected to be settable, not read-only.
    """

    id: str
    version: str
    host_api: str = ">=2.0 <3.0"

    def config_schema(self) -> dict[str, Any]:
        """Return an empty schema; unused by the registry under test."""
        return {}

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Unused stub; the registry under test never invokes strategies."""
        raise NotImplementedError


def test_register_and_get_exact_version() -> None:
    """A registered strategy can be fetched back by exact id/version."""
    registry = ReasoningStrategyRegistry()
    strategy = _FakeStrategy(id="autodev/reasoning-react", version="1.0.0")
    registry.register(strategy)
    assert registry.get("autodev/reasoning-react", "1.0.0") is strategy


def test_register_rejects_non_semver_version() -> None:
    """Registering a strategy with a non-SemVer version raises ValueError."""
    registry = ReasoningStrategyRegistry()
    strategy = _FakeStrategy(id="autodev/reasoning-react", version="not-a-version")
    with pytest.raises(ValueError, match="must be SemVer"):
        registry.register(strategy)


def test_register_rejects_incompatible_host_api() -> None:
    """Registering a strategy whose host_api excludes the platform version raises ValueError."""
    registry = ReasoningStrategyRegistry()
    strategy = _FakeStrategy(id="autodev/reasoning-react", version="1.0.0", host_api=">=9.0 <10.0")
    with pytest.raises(ValueError, match="incompatible"):
        registry.register(strategy)


def test_register_duplicate_version_without_replace_raises() -> None:
    """Registering the same id/version twice without replace=True raises ValueError."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))


def test_register_duplicate_version_with_replace_overwrites() -> None:
    """Registering the same id/version with replace=True overwrites the entry."""
    registry = ReasoningStrategyRegistry()
    first = _FakeStrategy(id="autodev/reasoning-react", version="1.0.0", host_api=">=2.0 <3.0")
    second = _FakeStrategy(id="autodev/reasoning-react", version="1.0.0", host_api="*")
    registry.register(first)
    registry.register(second, replace=True)
    assert registry.get("autodev/reasoning-react", "1.0.0") is second


def test_get_unknown_id_or_version_raises_key_error() -> None:
    """Fetching an unregistered id or version raises KeyError."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    with pytest.raises(KeyError):
        registry.get("autodev/unknown", "1.0.0")
    with pytest.raises(KeyError):
        registry.get("autodev/reasoning-react", "9.9.9")


def test_resolve_wildcard_returns_highest_version() -> None:
    """Resolving with the '*' constraint returns the highest registered version."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="2.1.0"))
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.5.0"))
    resolved = registry.resolve("autodev/reasoning-react")
    assert resolved.version == "2.1.0"


def test_resolve_with_constraint_filters_candidates() -> None:
    """Resolving with an explicit constraint only considers matching versions."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="2.1.0"))
    resolved = registry.resolve("autodev/reasoning-react", constraint="<2.0")
    assert resolved.version == "1.0.0"


def test_resolve_unknown_id_raises_key_error() -> None:
    """Resolving an id with no registered versions raises KeyError."""
    registry = ReasoningStrategyRegistry()
    with pytest.raises(KeyError, match="is not registered"):
        registry.resolve("autodev/unknown")


def test_resolve_no_version_satisfies_constraint_raises_key_error() -> None:
    """Resolving with a constraint that excludes every registered version raises KeyError."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    with pytest.raises(KeyError, match="no version"):
        registry.resolve("autodev/reasoning-react", constraint=">=5.0")


def test_resolve_invalid_constraint_raises_value_error() -> None:
    """Resolving with a syntactically invalid constraint raises ValueError."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    with pytest.raises(ValueError, match="invalid version constraint"):
        registry.resolve("autodev/reasoning-react", constraint="not a specifier!!")


def test_versions_sorted_descending_and_empty_for_unknown_id() -> None:
    """versions() returns descending SemVer order, or an empty tuple for an unknown id."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="2.0.0"))
    assert registry.versions("autodev/reasoning-react") == ("2.0.0", "1.0.0")
    assert registry.versions("autodev/unknown") == ()


def test_list_ids_returns_sorted_registered_ids() -> None:
    """list_ids() returns all registered ids in sorted order."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    registry.register(_FakeStrategy(id="autodev/reasoning-tot", version="1.0.0"))
    assert registry.list_ids() == ("autodev/reasoning-react", "autodev/reasoning-tot")


def test_unregister_whole_id_removes_all_versions() -> None:
    """unregister(id) with no version removes every registered version of that id."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="2.0.0"))
    registry.unregister("autodev/reasoning-react")
    assert registry.list_ids() == ()
    with pytest.raises(KeyError):
        registry.get("autodev/reasoning-react", "1.0.0")


def test_unregister_single_version_leaves_others_intact() -> None:
    """unregister(id, version) removes only that version, keeping siblings registered."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="2.0.0"))
    registry.unregister("autodev/reasoning-react", "1.0.0")
    assert registry.versions("autodev/reasoning-react") == ("2.0.0",)


def test_unregister_last_version_removes_id_entirely() -> None:
    """unregister(id, version) that removes the last version also drops the id itself."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    registry.unregister("autodev/reasoning-react", "1.0.0")
    assert registry.list_ids() == ()


def test_unregister_unknown_id_or_version_is_a_no_op() -> None:
    """unregister() on an unknown id, or an unknown version of a known id, does not raise."""
    registry = ReasoningStrategyRegistry()
    registry.register(_FakeStrategy(id="autodev/reasoning-react", version="1.0.0"))
    registry.unregister("autodev/unknown")
    registry.unregister("autodev/reasoning-react", "9.9.9")
    assert registry.versions("autodev/reasoning-react") == ("1.0.0",)


def test_is_host_compatible_wildcard_always_true() -> None:
    """A '*' host_api range is always compatible with the platform."""
    assert is_host_compatible("*") is True


def test_is_host_compatible_matching_range() -> None:
    """A host_api range that admits the platform version is compatible."""
    assert is_host_compatible(">=2.0 <3.0") is True
    assert is_host_compatible(f">={PLATFORM_HOST_VERSION}") is True


def test_is_host_compatible_excluding_range_is_false() -> None:
    """A host_api range that excludes the platform version is not compatible."""
    assert is_host_compatible(">=9.0 <10.0") is False


def test_is_host_compatible_invalid_expression_is_false() -> None:
    """A syntactically invalid host_api expression is treated as incompatible, not raised."""
    assert is_host_compatible("not a range!!") is False
