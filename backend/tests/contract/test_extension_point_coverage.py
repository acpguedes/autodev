"""Mandatory build gate: every extension-point kind must have a contract.

Parametrized over :class:`~backend.plugins.catalog.ExtensionPointKind` so
that adding a new kind to the catalog without registering it in
:data:`backend.tests.contract._harness.EXTENSION_POINT_CONTRACT_COVERAGE`
fails the build, per E12-S2-T1/T3.
"""

from __future__ import annotations

import importlib

import pytest

from backend.plugins.catalog import EXTENSION_POINTS, ExtensionPointKind
from backend.tests.contract._harness import (
    EXTENSION_POINT_CONTRACT_COVERAGE,
    ContractCoverageStatus,
)


@pytest.mark.parametrize("kind", list(ExtensionPointKind))
def test_every_catalog_kind_has_a_contract_registration(kind: ExtensionPointKind) -> None:
    """Every ``ExtensionPointKind`` must be registered as covered or pending.

    A kind with no entry at all -- e.g. one just added to
    ``EXTENSION_POINTS`` -- fails this test immediately, which is the
    mandatory build-gate behavior required by E12-S2-T3.
    """
    assert kind in EXTENSION_POINT_CONTRACT_COVERAGE, (
        f"ExtensionPointKind.{kind.name} is declared in "
        "backend.plugins.catalog.EXTENSION_POINTS but has no contract "
        "coverage registration in backend/tests/contract/_harness.py. "
        "Add a contract test module (COVERED) or an explicit rationale "
        "(PENDING) before merging."
    )

    coverage = EXTENSION_POINT_CONTRACT_COVERAGE[kind]
    assert coverage.note, f"ExtensionPointKind.{kind.name} coverage entry needs a note"

    if coverage.status is ContractCoverageStatus.COVERED:
        assert coverage.test_module, (
            f"ExtensionPointKind.{kind.name} is marked COVERED but declares "
            "no test_module"
        )
        importlib.import_module(coverage.test_module)
    else:
        assert coverage.test_module is None, (
            f"ExtensionPointKind.{kind.name} is marked PENDING but declares "
            "a test_module; mark it COVERED instead"
        )


def test_coverage_registry_has_no_stale_entries() -> None:
    """The registry must not reference kinds that no longer exist in the catalog."""
    stale = set(EXTENSION_POINT_CONTRACT_COVERAGE) - set(ExtensionPointKind)
    assert not stale, f"Stale contract coverage entries for removed kinds: {stale}"


def test_coverage_registry_matches_extension_points_catalog() -> None:
    """The registry must cover exactly the kinds declared in ``EXTENSION_POINTS``."""
    assert set(EXTENSION_POINT_CONTRACT_COVERAGE) == set(EXTENSION_POINTS)
