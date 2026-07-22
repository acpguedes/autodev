"""Contract test for the ``flow`` extension surface (E12-S2).

``flow`` is the orchestration-engine document format (``flow.yaml``) rather
than a catalog-registered :class:`~backend.plugins.catalog.ExtensionPointKind`
(its constituent node types -- ``agent``, ``skill``, ``tool`` -- reference
those catalog kinds), so this module is not parametrized through
``test_extension_point_coverage.py``. It asserts the same guarantee as the
other contract tests: :func:`~backend.flows.manifest.validate_flow_manifest`
round-trips a minimal valid document and rejects an invalid one.
"""

from __future__ import annotations

from backend.flows.manifest import FlowManifest, validate_flow_manifest


def _valid_flow_manifest() -> dict[str, object]:
    """Build a minimal, single-node valid ``flow.yaml`` document."""
    return {
        "schemaVersion": "1",
        "id": "autodev/flow-contract-probe",
        "version": "1.0.0",
        "name": "Contract Probe",
        "hostApi": ">=2.0 <3.0",
        "nodes": [
            {
                "id": "plan",
                "type": "agent",
                "ref": "autodev/agent-planner@>=1.0 <2.0",
            },
        ],
        "edges": [],
    }


def test_flow_manifest_round_trips_a_minimal_valid_document() -> None:
    """A minimal single-node flow.yaml document parses into a typed FlowManifest."""
    result = validate_flow_manifest(_valid_flow_manifest())

    assert result.valid is True
    assert result.errors == []
    assert isinstance(result.manifest, FlowManifest)
    assert result.manifest.id == "autodev/flow-contract-probe"
    assert [node.id for node in result.manifest.nodes] == ["plan"]


def test_flow_manifest_rejects_an_invalid_document() -> None:
    """A flow.yaml document with an edge to an unknown node is rejected."""
    raw = _valid_flow_manifest()
    raw["edges"] = [{"from": "plan", "to": "missing-node"}]

    result = validate_flow_manifest(raw)

    assert result.valid is False
    assert result.errors
    assert result.manifest is None
