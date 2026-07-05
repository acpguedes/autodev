"""Durable registry for the ``reasoning.strategy`` extension point (E4-S1).

Holds reasoning strategies keyed by id and SemVer version, resolves the latest
version matching a constraint, and rejects strategies whose ``host_api`` range
is incompatible with the platform. Mirrors the versioned registry pattern used
by the Agent Registry (E2) and Flow Registry (E3).
"""

from __future__ import annotations

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from backend.reasoning.contract import ReasoningStrategy

#: Platform host API version reasoning strategies are matched against.
PLATFORM_HOST_VERSION = "2.0"


class ReasoningStrategyRegistry:
    """In-memory registry of reasoning strategies keyed by id and version."""

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._by_id: dict[str, dict[str, ReasoningStrategy]] = {}

    def register(self, strategy: ReasoningStrategy, *, replace: bool = False) -> None:
        """Register a strategy version, enforcing host-API compatibility.

        Args:
            strategy: The strategy to register.
            replace: Whether to overwrite an already-registered version.

        Raises:
            ValueError: If the version is already registered (and ``replace`` is
                ``False``), the version is not valid SemVer, or the strategy's
                ``host_api`` range is incompatible with the platform.
        """
        if not _is_semver(strategy.version):
            raise ValueError(f"strategy version must be SemVer: {strategy.version!r}")
        if not is_host_compatible(strategy.host_api):
            raise ValueError(
                f"strategy {strategy.id} host_api {strategy.host_api!r} is incompatible "
                f"with platform {PLATFORM_HOST_VERSION}"
            )
        versions = self._by_id.setdefault(strategy.id, {})
        if strategy.version in versions and not replace:
            raise ValueError(f"strategy {strategy.id}@{strategy.version} already registered")
        versions[strategy.version] = strategy

    def get(self, strategy_id: str, version: str) -> ReasoningStrategy:
        """Return an exact strategy version.

        Args:
            strategy_id: Identifier of the strategy.
            version: Exact SemVer version to fetch.

        Returns:
            The registered strategy.

        Raises:
            KeyError: If no such id/version is registered.
        """
        try:
            return self._by_id[strategy_id][version]
        except KeyError as exc:
            raise KeyError(f"strategy {strategy_id}@{version} is not registered") from exc

    def resolve(self, strategy_id: str, constraint: str = "*") -> ReasoningStrategy:
        """Resolve the latest registered version matching a constraint.

        Args:
            strategy_id: Identifier of the strategy.
            constraint: PEP 440/SemVer specifier (e.g. ``">=1.0 <2.0"``), or
                ``"*"`` for any version.

        Returns:
            The highest-versioned strategy satisfying the constraint.

        Raises:
            KeyError: If the id is unknown or no version satisfies the constraint.
            ValueError: If the constraint is not a valid specifier.
        """
        versions = self._by_id.get(strategy_id)
        if not versions:
            raise KeyError(f"strategy {strategy_id} is not registered")
        candidates = sorted(versions, key=Version, reverse=True)
        if constraint != "*":
            spec = _specifier(constraint)
            candidates = [version for version in candidates if spec.contains(version, prereleases=True)]
        if not candidates:
            raise KeyError(f"no version of {strategy_id} satisfies constraint {constraint!r}")
        return versions[candidates[0]]

    def versions(self, strategy_id: str) -> tuple[str, ...]:
        """Return the registered versions of a strategy, newest first.

        Args:
            strategy_id: Identifier of the strategy.

        Returns:
            Registered versions sorted descending; empty if the id is unknown.
        """
        versions = self._by_id.get(strategy_id, {})
        return tuple(sorted(versions, key=Version, reverse=True))

    def list_ids(self) -> tuple[str, ...]:
        """Return the ids of all registered strategies, sorted."""
        return tuple(sorted(self._by_id))

    def unregister(self, strategy_id: str, version: str | None = None) -> None:
        """Remove a strategy id, or a single version of it.

        Args:
            strategy_id: Identifier of the strategy to remove.
            version: Specific version to remove; removes the whole id if ``None``.
        """
        if version is None:
            self._by_id.pop(strategy_id, None)
            return
        versions = self._by_id.get(strategy_id)
        if versions is not None:
            versions.pop(version, None)
            if not versions:
                self._by_id.pop(strategy_id, None)


def is_host_compatible(host_api: str, platform_version: str = PLATFORM_HOST_VERSION) -> bool:
    """Check whether a strategy's ``host_api`` range admits the platform version.

    Args:
        host_api: The strategy's supported host API range, or ``"*"``.
        platform_version: The platform host API version to test.

    Returns:
        ``True`` if the platform version satisfies the range, ``False`` otherwise.
    """
    if host_api == "*":
        return True
    try:
        return _specifier(host_api).contains(platform_version, prereleases=True)
    except (InvalidSpecifier, ValueError):
        return False


def _specifier(expression: str) -> SpecifierSet:
    """Parse a space- or comma-separated version range into a ``SpecifierSet``.

    Args:
        expression: Range expression, e.g. ``">=2.0 <3.0"``.

    Returns:
        The parsed specifier set.

    Raises:
        ValueError: If the expression is not a valid specifier set.
    """
    try:
        return SpecifierSet(expression.replace(" ", ","))
    except InvalidSpecifier as exc:
        raise ValueError(f"invalid version constraint: {expression!r}") from exc


def _is_semver(value: str) -> bool:
    """Check whether a string is a valid SemVer version.

    Args:
        value: Candidate version string.

    Returns:
        ``True`` if valid SemVer, ``False`` otherwise.
    """
    try:
        Version(value)
    except InvalidVersion:
        return False
    return True


__all__ = ["PLATFORM_HOST_VERSION", "ReasoningStrategyRegistry", "is_host_compatible"]
