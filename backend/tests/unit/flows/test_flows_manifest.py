"""E3-S1 tests: flow.yaml parsing, graph validation, versioning, expressions."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

import pytest

from backend.flows.expressions import (
    ExpressionError,
    compile_expression,
    evaluate_expression,
    render_template,
)
from backend.flows.manifest import (
    FLOW_NODE_TYPES,
    FLOW_SCHEMA_VERSION,
    TRIGGER_TYPES,
    validate_flow_manifest,
    version_in_range,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "flows" / "schemas" / "flow.schema.json"
)


def _all_node_types_flow() -> dict[str, Any]:
    """Build a valid manifest document exercising every canonical node type."""
    return {
        "schemaVersion": "1",
        "id": "autodev/flow-e2e",
        "version": "1.0.0",
        "name": "E2E",
        "hostApi": ">=2.0 <3.0",
        "triggers": [
            {"type": "message"},
            {"type": "event", "on": "flow.run.requested"},
            {"type": "cron", "schedule": "0 * * * *"},
            {"type": "webhook"},
        ],
        "input": {
            "schemaVersion": "1",
            "type": "object",
            "required": ["task"],
            "properties": {"task": {"type": "string"}, "items": {"type": "array"}},
        },
        "defaults": {
            "retries": {"maxAttempts": 2, "backoff": "fixed", "initialDelaySec": 0},
            "timeoutSec": 60,
        },
        "nodes": [
            {
                "id": "plan",
                "type": "agent",
                "ref": "autodev/agent-planner@>=1.0 <2.0",
                "input": {"task": "{{ flow.input.task }}"},
            },
            {"id": "code", "type": "agent", "ref": "autodev/agent-coder@1.0.0"},
            {
                "id": "apply",
                "type": "skill",
                "ref": "autodev/skill-apply-patch",
                "input": {"patch": "{{ nodes.code.output.patch }}"},
            },
            {"id": "lint", "type": "tool", "ref": "autodev/tool-linter"},
            {"id": "gate", "type": "conditional"},
            {
                "id": "review",
                "type": "human",
                "prompt": "Approve?",
                "form": {
                    "type": "object",
                    "required": ["decision"],
                    "properties": {"decision": {"enum": ["approve", "reject"]}},
                },
                "timeoutSec": 3600,
                "onTimeout": "escalate",
            },
            {
                "id": "fan-out",
                "type": "map",
                "ref": "autodev/flow-item-worker",
                "over": "{{ flow.input.items }}",
                "maxParallel": 4,
            },
            {"id": "escalate", "type": "subflow", "ref": "autodev/flow-escalation"},
        ],
        "edges": [
            {"from": "plan", "to": "code"},
            {"from": "code", "to": "apply"},
            {"from": "apply", "to": "lint"},
            {"from": "lint", "to": "gate"},
            {
                "from": "gate",
                "to": "review",
                "when": "{{ nodes.lint.output.ok == true }}",
            },
            {
                "from": "gate",
                "to": "code",
                "when": "{{ nodes.lint.output.ok == false }}",
            },
            {
                "from": "review",
                "to": "fan-out",
                "when": "{{ nodes.review.output.decision == 'approve' }}",
            },
            {"from": "review", "to": "escalate", "on": "timeout"},
        ],
        "budgets": {"maxCostUsd": 5.0, "maxWallClockSec": 600, "maxTokens": 100000},
    }


class TestManifestValidation:
    """E3-S1 functional criteria."""

    def test_flow_with_every_node_type_validates(self) -> None:
        """A flow using all seven canonical node types passes validation."""
        result = validate_flow_manifest(_all_node_types_flow())
        assert result.errors == []
        assert result.valid
        assert result.manifest is not None
        assert {node.type for node in result.manifest.nodes} == set(FLOW_NODE_TYPES)
        assert result.manifest.entry_node().id == "plan"

    def test_missing_required_fields_rejected(self) -> None:
        """Every required top-level field is enforced."""
        result = validate_flow_manifest({})
        for key in ("schemaVersion", "id", "version", "hostApi", "nodes", "edges"):
            assert any(key in error for error in result.errors)

    def test_bad_id_version_and_host_api_rejected(self) -> None:
        """Identifier, SemVer, and hostApi formats are enforced."""
        raw = _all_node_types_flow()
        raw["id"] = "NotKebab"
        raw["version"] = "1.0"
        raw["hostApi"] = "not-a-range"
        result = validate_flow_manifest(raw)
        assert any("namespace/name" in error for error in result.errors)
        assert any("SemVer" in error for error in result.errors)
        assert any("hostApi" in error for error in result.errors)

    def test_schema_version_pinned(self) -> None:
        """Unknown manifest schema versions are rejected."""
        raw = _all_node_types_flow()
        raw["schemaVersion"] = "9"
        result = validate_flow_manifest(raw)
        assert any("schemaVersion" in error for error in result.errors)

    def test_unknown_node_type_rejected(self) -> None:
        """Node types outside the canonical vocabulary are rejected."""
        raw = _all_node_types_flow()
        raw["nodes"][0]["type"] = "robot"
        result = validate_flow_manifest(raw)
        assert any("type must be one of" in error for error in result.errors)

    def test_validation_under_100ms(self) -> None:
        """E3-S1 non-functional criterion: validation < 100 ms."""
        raw = _all_node_types_flow()
        started = time.perf_counter()
        for _ in range(10):
            assert validate_flow_manifest(copy.deepcopy(raw)).valid
        elapsed_ms = (time.perf_counter() - started) * 1000 / 10
        assert elapsed_ms < 100


class TestGraphValidation:
    """Invalid graphs are rejected (E3-S1-T2)."""

    def test_duplicate_node_ids_rejected(self) -> None:
        """Two nodes with the same id are rejected."""
        raw = _all_node_types_flow()
        raw["nodes"][1]["id"] = "plan"
        result = validate_flow_manifest(raw)
        assert any("duplicate node id" in error for error in result.errors)

    def test_edge_to_unknown_node_rejected(self) -> None:
        """Edges must reference declared nodes."""
        raw = _all_node_types_flow()
        raw["edges"][0]["to"] = "ghost"
        result = validate_flow_manifest(raw)
        assert any("unknown node 'ghost'" in error for error in result.errors)

    def test_unreachable_node_rejected(self) -> None:
        """Nodes not reachable from the entry are rejected."""
        raw = _all_node_types_flow()
        raw["nodes"].append({"id": "lost-a", "type": "tool", "ref": "autodev/tool-x"})
        raw["nodes"].append({"id": "lost-b", "type": "tool", "ref": "autodev/tool-y"})
        raw["edges"].append({"from": "lost-a", "to": "lost-b"})
        raw["edges"].append(
            {"from": "lost-b", "to": "lost-a", "when": "{{ flow.input.task == 'x' }}"}
        )
        result = validate_flow_manifest(raw)
        assert any("unreachable nodes" in error for error in result.errors)

    def test_multiple_entry_nodes_rejected(self) -> None:
        """A flow with two nodes lacking incoming edges has no single entry."""
        raw = _all_node_types_flow()
        raw["nodes"].append({"id": "island", "type": "tool", "ref": "autodev/tool-y"})
        result = validate_flow_manifest(raw)
        assert any("exactly one entry node" in error for error in result.errors)

    def test_unconditional_cycle_rejected(self) -> None:
        """A loop with no guarded edge can never terminate and is rejected."""
        raw = {
            "schemaVersion": "1",
            "id": "autodev/flow-loop",
            "version": "1.0.0",
            "hostApi": ">=2.0 <3.0",
            "nodes": [
                {"id": "start", "type": "tool", "ref": "autodev/tool-a"},
                {"id": "a", "type": "tool", "ref": "autodev/tool-b"},
                {"id": "b", "type": "tool", "ref": "autodev/tool-c"},
                {"id": "end", "type": "tool", "ref": "autodev/tool-d"},
            ],
            "edges": [
                {"from": "start", "to": "a"},
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a"},
                {"from": "a", "to": "end", "when": "{{ flow.input.done == true }}"},
            ],
        }
        result = validate_flow_manifest(raw)
        assert any("unconditional cycle" in error for error in result.errors)

    def test_guarded_rework_loop_allowed(self) -> None:
        """Loops broken by a guarded edge (rework paths) are legal."""
        result = validate_flow_manifest(_all_node_types_flow())
        assert result.valid

    def test_conditional_node_requires_guarded_edges(self) -> None:
        """Conditional nodes must guard every outgoing edge and have >= 2."""
        raw = _all_node_types_flow()
        raw["edges"][4] = {"from": "gate", "to": "review"}
        result = validate_flow_manifest(raw)
        assert any(
            "must guard every outgoing edge" in error for error in result.errors
        )

    def test_ambiguous_unguarded_fanout_rejected(self) -> None:
        """A non-conditional node may have at most one unguarded out-edge."""
        raw = _all_node_types_flow()
        raw["edges"].append({"from": "plan", "to": "lint"})
        result = validate_flow_manifest(raw)
        assert any("unguarded outgoing edges" in error for error in result.errors)

    def test_timeout_edge_only_from_human(self) -> None:
        """'on: timeout' edges are only legal leaving human nodes."""
        raw = _all_node_types_flow()
        raw["edges"].append({"from": "plan", "to": "escalate", "on": "timeout"})
        result = validate_flow_manifest(raw)
        assert any(
            "only allowed on edges leaving human nodes" in error
            for error in result.errors
        )

    def test_on_timeout_must_match_edge(self) -> None:
        """A human node's onTimeout must match an 'on: timeout' edge target."""
        raw = _all_node_types_flow()
        raw["nodes"][5]["onTimeout"] = "fan-out"
        result = validate_flow_manifest(raw)
        assert any("does not match" in error for error in result.errors)

    def test_binding_referencing_unknown_node_rejected(self) -> None:
        """Input bindings may only reference declared nodes."""
        raw = _all_node_types_flow()
        raw["nodes"][2]["input"]["patch"] = "{{ nodes.ghost.output.patch }}"
        result = validate_flow_manifest(raw)
        assert any("references unknown node 'ghost'" in error for error in result.errors)

    def test_binding_referencing_undeclared_input_rejected(self) -> None:
        """flow.input references must exist in the declared input schema."""
        raw = _all_node_types_flow()
        raw["nodes"][0]["input"]["task"] = "{{ flow.input.missing }}"
        result = validate_flow_manifest(raw)
        assert any(
            "flow.input.missing is not declared" in error for error in result.errors
        )

    def test_human_and_map_field_requirements(self) -> None:
        """human nodes need a prompt; map nodes need 'over'."""
        raw = _all_node_types_flow()
        del raw["nodes"][5]["prompt"]
        del raw["nodes"][6]["over"]
        result = validate_flow_manifest(raw)
        assert any("prompt is required" in error for error in result.errors)
        assert any("over is required" in error for error in result.errors)


class TestConditionalEdgePredicates:
    """A conditional edge evaluates a predicate over run state (E3-S1)."""

    def test_predicate_evaluates_over_state(self) -> None:
        """The manifest's 'when' expression evaluates against run state."""
        raw = _all_node_types_flow()
        manifest = validate_flow_manifest(raw).manifest
        assert manifest is not None
        edge = manifest.edges_from("gate")[0]
        assert edge.when is not None
        expression = edge.when.strip().removeprefix("{{").removesuffix("}}")
        state_pass = {"nodes": {"lint": {"output": {"ok": True}}}}
        state_fail = {"nodes": {"lint": {"output": {"ok": False}}}}
        assert evaluate_expression(expression, state_pass) is True
        assert evaluate_expression(expression, state_fail) is False

    def test_bracket_paths_and_boolean_operators(self) -> None:
        """Quoted bracket segments and and/or/not compose correctly."""
        state = {
            "nodes": {"apply-and-validate": {"output": {"testsPassed": True, "n": 3}}}
        }
        assert (
            evaluate_expression(
                "nodes['apply-and-validate'].output.testsPassed == true", state
            )
            is True
        )
        assert (
            evaluate_expression(
                "nodes['apply-and-validate'].output.n > 1 and not "
                "(nodes['apply-and-validate'].output.n > 5)",
                state,
            )
            is True
        )

    def test_missing_paths_resolve_to_null(self) -> None:
        """Optional state is testable with == null."""
        assert evaluate_expression("nodes.x.output.y == null", {"nodes": {}}) is True

    def test_invalid_syntax_raises(self) -> None:
        """Broken expressions raise ExpressionError."""
        with pytest.raises(ExpressionError):
            compile_expression("nodes..output ==")
        with pytest.raises(ExpressionError):
            evaluate_expression("1 < 'a'", {})

    def test_render_template_preserves_types_and_interpolates(self) -> None:
        """Full templates keep value types; embedded templates interpolate."""
        state = {"flow": {"input": {"task": "fix", "count": 2}}}
        assert render_template("{{ flow.input.count }}", state) == 2
        assert render_template("task: {{ flow.input.task }}!", state) == "task: fix!"
        rendered = render_template({"t": ["{{ flow.input.task }}"]}, state)
        assert rendered == {"t": ["fix"]}


class TestVersioning:
    """Flow versioning (E3-S1-T3)."""

    def test_version_in_range(self) -> None:
        """Exact versions, ranges, and wildcard all resolve correctly."""
        assert version_in_range("1.2.3", "*")
        assert version_in_range("1.2.3", "1.2.3")
        assert not version_in_range("1.2.4", "1.2.3")
        assert version_in_range("1.5.0", ">=1.0 <2.0")
        assert not version_in_range("2.0.0", ">=1.0 <2.0")

    def test_node_ref_ranges_parsed(self) -> None:
        """Node refs carry their SemVer range for registry resolution."""
        manifest = validate_flow_manifest(_all_node_types_flow()).manifest
        assert manifest is not None
        plan = manifest.node("plan")
        assert plan.ref is not None
        assert plan.ref.id == "autodev/agent-planner"
        assert plan.ref.version_range == ">=1.0 <2.0"
        apply_node = manifest.node("apply")
        assert apply_node.ref is not None
        assert apply_node.ref.version_range == "*"

    def test_invalid_ref_range_rejected(self) -> None:
        """Malformed ref ranges are rejected."""
        raw = _all_node_types_flow()
        raw["nodes"][0]["ref"] = "autodev/agent-planner@banana"
        result = validate_flow_manifest(raw)
        assert any("invalid version range" in error for error in result.errors)


class TestSchemaContract:
    """The published JSON schema stays in lockstep with the validator."""

    def test_schema_file_matches_validator_vocabulary(self) -> None:
        """Node types, trigger types, and required keys agree with the code."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert schema["properties"]["schemaVersion"]["const"] == FLOW_SCHEMA_VERSION
        node_enum = set(
            schema["properties"]["nodes"]["items"]["properties"]["type"]["enum"]
        )
        assert node_enum == set(FLOW_NODE_TYPES)
        trigger_enum = set(
            schema["properties"]["triggers"]["items"]["properties"]["type"]["enum"]
        )
        assert trigger_enum == set(TRIGGER_TYPES)
        assert set(schema["required"]) == {
            "schemaVersion",
            "id",
            "version",
            "hostApi",
            "nodes",
            "edges",
        }

    def test_manifest_available_from_sdk(self) -> None:
        """The flow contract is exported through the SDK surface."""
        from backend.sdk.contracts import FlowManifest as SdkFlowManifest

        manifest = validate_flow_manifest(_all_node_types_flow()).manifest
        assert isinstance(manifest, SdkFlowManifest)

    def test_template_example_manifest_validates(self) -> None:
        """The repo's canonical flow.yaml example parses and validates."""
        import yaml

        example = (
            Path(__file__).resolve().parents[4]
            / "docs"
            / "v2_platform"
            / "templates"
            / "manifests"
            / "flow.yaml.example"
        )
        raw = yaml.safe_load(example.read_text(encoding="utf-8"))
        result = validate_flow_manifest(raw)
        assert result.errors == []
