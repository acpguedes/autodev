"""Extension-point contract test tier (E12-S2).

Tests under this package verify that every kind in
:class:`backend.plugins.catalog.ExtensionPointKind` has a stable, documented
contract: a Protocol/ABC shape that does not silently change, and (where the
extension point has a manifest format) a validator that round-trips a
minimal valid document and rejects an invalid one.

This tier is collected by pytest as part of ``backend/tests`` (see
``PYTEST_PATHS`` in the ``Makefile``) and counts toward the project's 85%
backend coverage gate; no separate CI wiring is required. See
``docs/testing.md`` for the full description of what each extension point
guarantees and why a green contract suite is the mandatory prerequisite for
Marketplace (E13) publication.
"""

from __future__ import annotations
