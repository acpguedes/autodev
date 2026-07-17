"""Unit tests for backend/routing/policy_parsing.py (E5-S1, E5-S2).

Covers ``validate_routing_policy``, ``load_routing_policy``, and their
private helpers: required-field checks, id/version/hostApi format
validation, router pipeline stage parsing (rules/embeddings/llm-router),
rule predicate validation (including the ``~=`` regex pre-compilation),
constraints parsing, and the router.default fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.routing.policy import (
    RouterEmbeddingsStageSpec,
    RouterLLMStageSpec,
    RouterRulesStageSpec,
)
from backend.routing.policy_parsing import (
    POLICY_ID_RE,
    SEMVER_RE,
    load_routing_policy,
    validate_routing_policy,
)


def _minimal_raw(**overrides: Any) -> dict[str, Any]:
    """Build a minimal valid raw routing-policy document, with overrides applied."""
    base: dict[str, Any] = {
        "schemaVersion": "1",
        "id": "autodev/routing-policy-test",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "router": {"pipeline": []},
    }
    base.update(overrides)
    return base


def test_missing_required_top_level_keys_are_all_reported() -> None:
    """Every required top-level key absent from the document is reported."""
    result = validate_routing_policy({})
    assert result.valid is False
    assert result.policy is None
    for key in ("schemaVersion", "id", "version", "hostApi", "router"):
        assert f"{key} is required" in result.errors


def test_minimal_valid_document_parses_successfully() -> None:
    """A minimal, well-formed document validates with no errors."""
    result = validate_routing_policy(_minimal_raw())
    assert result.valid is True
    assert result.errors == []
    assert result.policy is not None
    assert result.policy.id == "autodev/routing-policy-test"
    assert result.policy.version == "1.0.0"


def test_invalid_id_format_rejected() -> None:
    """An id not matching namespace/name kebab-case is rejected."""
    result = validate_routing_policy(_minimal_raw(id="Not Valid!!"))
    assert result.valid is False
    assert "id must use namespace/name kebab-case format" in result.errors


def test_invalid_version_format_rejected() -> None:
    """A non-SemVer version string is rejected."""
    result = validate_routing_policy(_minimal_raw(version="not-a-version"))
    assert result.valid is False
    assert "version must be SemVer MAJOR.MINOR.PATCH" in result.errors


def test_invalid_host_api_range_rejected() -> None:
    """An unparsable hostApi specifier is rejected."""
    result = validate_routing_policy(_minimal_raw(hostApi="???"))
    assert result.valid is False
    assert "hostApi must be a supported range expression" in result.errors


def test_host_api_wildcard_is_accepted() -> None:
    """A wildcard '*' hostApi is treated as valid."""
    result = validate_routing_policy(_minimal_raw(hostApi="*"))
    assert result.valid is True


def test_required_string_field_wrong_type_reports_error() -> None:
    """A required field present but not a string (e.g. YAML-parsed float) is rejected."""
    result = validate_routing_policy(_minimal_raw(version=1.0))
    assert result.valid is False
    assert "version must be a string" in result.errors


def test_router_not_an_object_rejected() -> None:
    """A non-dict router section is rejected and treated as an empty pipeline."""
    result = validate_routing_policy(_minimal_raw(router=["nope"]))
    assert result.valid is False
    assert "router must be an object" in result.errors


def test_router_pipeline_not_a_list_rejected() -> None:
    """A non-list router.pipeline is rejected."""
    result = validate_routing_policy(_minimal_raw(router={"pipeline": "oops"}))
    assert result.valid is False
    assert "router.pipeline must be a list" in result.errors


def test_router_stage_unknown_kind_rejected() -> None:
    """An unrecognized router stage kind is rejected."""
    result = validate_routing_policy(
        _minimal_raw(router={"pipeline": [{"kind": "bogus"}]})
    )
    assert result.valid is False
    assert any("pipeline[0].kind must be one of" in e for e in result.errors)


def test_rules_stage_valid_rule_with_confidence() -> None:
    """A well-formed rules stage with a valid rule parses successfully."""
    raw = _minimal_raw(
        router={
            "pipeline": [
                {
                    "kind": "rules",
                    "confidence_floor": 0.2,
                    "rules": [
                        {
                            "when": {"task.kind": "code_patch"},
                            "set": {
                                "task_type": "patch",
                                "path": ["agent-a", "agent-b"],
                            },
                            "confidence": 0.9,
                        }
                    ],
                }
            ]
        }
    )
    result = validate_routing_policy(raw)
    assert result.valid is True
    assert result.policy is not None
    stage = result.policy.router.stages[0]
    assert isinstance(stage, RouterRulesStageSpec)
    assert stage.confidence_floor == 0.2
    assert len(stage.rules) == 1
    assert stage.rules[0].confidence == 0.9


def test_rules_stage_rules_not_a_list_rejected() -> None:
    """A non-list rules field within a rules stage is rejected."""
    result = validate_routing_policy(
        _minimal_raw(router={"pipeline": [{"kind": "rules", "rules": "oops"}]})
    )
    assert result.valid is False
    assert any("rules must be a list" in e for e in result.errors)


def test_rule_missing_when_rejected() -> None:
    """A rule without a non-empty 'when' mapping is rejected."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [
                    {
                        "kind": "rules",
                        "rules": [{"set": {"task_type": "x", "path": []}}],
                    }
                ]
            }
        )
    )
    assert result.valid is False
    assert any("when must be a non-empty object" in e for e in result.errors)


def test_rule_missing_set_fields_rejected() -> None:
    """A rule whose 'set' lacks task_type/path is rejected."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [
                    {
                        "kind": "rules",
                        "rules": [{"when": {"a": "b"}, "set": {"task_type": "x"}}],
                    }
                ]
            }
        )
    )
    assert result.valid is False
    assert any(
        "set must be an object with task_type and path" in e for e in result.errors
    )


def test_rule_set_path_not_list_of_strings_rejected() -> None:
    """A rule's set.path containing non-string entries is rejected."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [
                    {
                        "kind": "rules",
                        "rules": [
                            {
                                "when": {"a": "b"},
                                "set": {"task_type": "x", "path": [1, 2]},
                            }
                        ],
                    }
                ]
            }
        )
    )
    assert result.valid is False
    assert any("set.path must be a list of strings" in e for e in result.errors)


def test_rule_with_invalid_regex_predicate_rejected() -> None:
    """A '~=' predicate with an unparsable regex is rejected at parse time."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [
                    {
                        "kind": "rules",
                        "rules": [
                            {
                                "when": {"task.kind": "~=(unclosed["},
                                "set": {"task_type": "x", "path": ["a"]},
                            }
                        ],
                    }
                ]
            }
        )
    )
    assert result.valid is False
    assert any("invalid regex pattern" in e for e in result.errors)


def test_rule_with_valid_regex_predicate_and_slash_delimiters() -> None:
    """A '~=' predicate wrapped in slashes is unwrapped and compiles cleanly."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [
                    {
                        "kind": "rules",
                        "rules": [
                            {
                                "when": {"task.kind": "~= /^code_.*$/"},
                                "set": {"task_type": "x", "path": ["a"]},
                            }
                        ],
                    }
                ]
            }
        )
    )
    assert result.valid is True


def test_rule_set_constraints_invalid_type_rejected() -> None:
    """A rule's set.constraints, if present and invalid, is validated too."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [
                    {
                        "kind": "rules",
                        "rules": [
                            {
                                "when": {"a": "b"},
                                "set": {
                                    "task_type": "x",
                                    "path": ["a"],
                                    "constraints": "nope",
                                },
                            }
                        ],
                    }
                ]
            }
        )
    )
    assert result.valid is False
    assert any(
        "set.constraints must be an object" in e for e in result.errors
    )


def test_embeddings_stage_missing_dataset_rejected() -> None:
    """An embeddings stage without a dataset is rejected."""
    result = validate_routing_policy(
        _minimal_raw(router={"pipeline": [{"kind": "embeddings"}]})
    )
    assert result.valid is False
    assert any("dataset is required" in e for e in result.errors)


def test_embeddings_stage_valid() -> None:
    """A well-formed embeddings stage parses successfully."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [
                    {"kind": "embeddings", "dataset": "task-embeds", "threshold": 0.8}
                ]
            }
        )
    )
    assert result.valid is True
    assert result.policy is not None
    stage = result.policy.router.stages[0]
    assert isinstance(stage, RouterEmbeddingsStageSpec)
    assert stage.dataset == "task-embeds"
    assert stage.threshold == 0.8


def test_llm_router_stage_missing_model_rejected() -> None:
    """An llm-router stage without a model is rejected."""
    result = validate_routing_policy(
        _minimal_raw(router={"pipeline": [{"kind": "llm-router"}]})
    )
    assert result.valid is False
    assert any("model is required" in e for e in result.errors)


def test_llm_router_stage_valid() -> None:
    """A well-formed llm-router stage parses successfully."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [
                    {
                        "kind": "llm-router",
                        "model": "gpt-4",
                        "max_cost_usd": 0.1,
                        "only_if_confidence_below": 0.5,
                    }
                ]
            }
        )
    )
    assert result.valid is True
    assert result.policy is not None
    stage = result.policy.router.stages[0]
    assert isinstance(stage, RouterLLMStageSpec)
    assert stage.model == "gpt-4"
    assert stage.max_cost_usd == 0.1


def test_router_default_not_object_uses_generic_default() -> None:
    """A non-dict router.default is rejected and replaced by the generic default."""
    result = validate_routing_policy(_minimal_raw(router={"pipeline": [], "default": "oops"}))
    assert result.valid is False
    assert "router.default must be an object" in result.errors


def test_router_default_custom_values_parsed() -> None:
    """A well-formed router.default is parsed with its custom fields."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [],
                "default": {
                    "task_type": "custom",
                    "intent": "custom-intent",
                    "path": ["fallback-agent"],
                    "confidence": 0.3,
                    "rationale": "custom rationale",
                },
            }
        )
    )
    assert result.valid is True
    assert result.policy is not None
    default = result.policy.router.default
    assert default.task_type == "custom"
    assert default.path == ("fallback-agent",)
    assert default.rationale == "custom rationale"


def test_router_default_absent_falls_back_to_generic() -> None:
    """When router.default is absent entirely, the generic default is used."""
    result = validate_routing_policy(_minimal_raw(router={"pipeline": []}))
    assert result.valid is True
    assert result.policy is not None
    default = result.policy.router.default
    assert default.task_type == "existing-repo-change"
    assert default.path == (
        "navigator",
        "analyzer",
        "architect",
        "coder",
        "devops",
        "validator",
        "responder",
    )


def test_router_constraints_invalid_type_rejected() -> None:
    """A non-dict router.constraints is rejected."""
    result = validate_routing_policy(
        _minimal_raw(router={"pipeline": [], "constraints": "nope"})
    )
    assert result.valid is False
    assert any("router.constraints must be an object" in e for e in result.errors)


def test_router_constraints_invalid_latency_class_rejected() -> None:
    """An invalid latency_class value in constraints is rejected."""
    result = validate_routing_policy(
        _minimal_raw(
            router={
                "pipeline": [],
                "constraints": {"latency_class": "warp-speed"},
            }
        )
    )
    assert result.valid is False
    assert any("latency_class must be one of" in e for e in result.errors)


def test_router_constraints_negative_cost_rejected() -> None:
    """A negative max_cost_usd in constraints is rejected."""
    result = validate_routing_policy(
        _minimal_raw(
            router={"pipeline": [], "constraints": {"max_cost_usd": -1.0}}
        )
    )
    assert result.valid is False
    assert any("max_cost_usd must be a non-negative number" in e for e in result.errors)


def test_policy_id_regex_accepts_and_rejects_expected_shapes() -> None:
    """Sanity-check POLICY_ID_RE against representative valid/invalid ids."""
    assert POLICY_ID_RE.match("autodev/routing-policy")
    assert POLICY_ID_RE.match("a/b")
    assert not POLICY_ID_RE.match("NoSlash")
    assert not POLICY_ID_RE.match("Upper/Case")


def test_semver_regex_accepts_and_rejects_expected_shapes() -> None:
    """Sanity-check SEMVER_RE against representative valid/invalid versions."""
    assert SEMVER_RE.match("1.0.0")
    assert SEMVER_RE.match("2.10.3-beta.1")
    assert not SEMVER_RE.match("1.0")
    assert not SEMVER_RE.match("v1.0.0")


def test_load_routing_policy_success(tmp_path: Path) -> None:
    """load_routing_policy reads, parses, and validates a YAML file from disk."""
    policy_file = tmp_path / "routing-policy.yaml"
    policy_file.write_text(
        "schemaVersion: '1'\n"
        "id: autodev/routing-policy-file\n"
        "version: 1.0.0\n"
        "hostApi: '*'\n"
        "router:\n"
        "  pipeline: []\n",
        encoding="utf-8",
    )
    policy = load_routing_policy(policy_file)
    assert policy.id == "autodev/routing-policy-file"


def test_load_routing_policy_rejects_non_mapping_document(tmp_path: Path) -> None:
    """load_routing_policy raises ValueError when the YAML root is not a mapping."""
    policy_file = tmp_path / "routing-policy.yaml"
    policy_file.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a mapping"):
        load_routing_policy(policy_file)


def test_load_routing_policy_propagates_validation_errors(tmp_path: Path) -> None:
    """load_routing_policy raises ValueError with joined messages on invalid content."""
    policy_file = tmp_path / "routing-policy.yaml"
    policy_file.write_text("id: not valid\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_routing_policy(policy_file)
