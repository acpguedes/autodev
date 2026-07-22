"""Standalone ``hostApi`` SemVer compatibility helper for the plugin SDK.

Plugin authors and contract tests can use :func:`check_host_api_compatibility`
to check a manifest's declared ``hostApi`` range against a host version
without instantiating a :class:`~backend.plugins.host.PluginHost`. This is a
thin wrapper over :mod:`packaging`; it intentionally mirrors the comparison
:class:`~backend.plugins.host.PluginHost` performs internally
(``PluginHost._compatibility_reason``) rather than reimplementing plugin
install/lifecycle logic, so the two never drift silently -- the actual
install-time compatibility gate for plugins remains
:class:`~backend.plugins.host.PluginHost`, and contract tests should assert
against that real path first.
"""

from __future__ import annotations

from packaging.specifiers import SpecifierSet
from packaging.version import Version


def check_host_api_compatibility(host_api_range: str, host_version: str) -> bool:
    """Check whether a declared ``hostApi`` range is satisfied by a host version.

    Args:
        host_api_range: A manifest's ``hostApi`` SemVer range expression,
            e.g. ``">=2.0 <3.0"`` (space- or comma-separated clauses are
            both accepted, matching the ``plugin.yaml``/``agent.yaml``/
            ``skill.yaml``/``flow.yaml`` manifest formats).
        host_version: The host's SemVer version, e.g. ``"2.0.0"``.

    Returns:
        ``True`` if ``host_version`` satisfies ``host_api_range``, ``False``
        otherwise.
    """
    specifier = SpecifierSet(host_api_range.replace(" ", ","))
    return Version(host_version) in specifier


__all__ = ["check_host_api_compatibility"]
