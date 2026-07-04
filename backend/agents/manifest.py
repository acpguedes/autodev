"""agent.yaml parsing, validation, and strict IO checks for v2 agents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from backend.agents.capabilities import CAPABILITY_IDS

AGENT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")
CONTRACT_ID_RE = AGENT_ID_RE
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
ENTRYPOINT_REF_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_][\w.]*$")
VALID_LEVELS = frozenset({"primary", "secondary"})
VALID_INVALID_OUTPUT_ACTIONS = frozenset({"repair-then-fail", "fail", "passthrough"})


class ValidationError(ValueError):
    """Raised when agent IO violates its declared schema."""


@dataclass(frozen=True)
class AgentBudgets:
    tokens_input: int
    tokens_output: int
    cost_usd: float
    wall_clock_seconds: int
    max_steps: int
    max_tool_calls: int
    on_exceeded: str = "fail-closed"


DEFAULT_AGENT_BUDGETS = AgentBudgets(
    tokens_input=120000,
    tokens_output=16000,
    cost_usd=0.75,
    wall_clock_seconds=180,
    max_steps=24,
    max_tool_calls=40,
)


@dataclass(frozen=True)
class AgentCapability:
    id: str
    version: str
    level: str = "primary"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentIOContract:
    contract: str
    contract_version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    on_invalid_output: str = "fail"


@dataclass(frozen=True)
class AgentToolPermission:
    id: str
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSkillPermission:
    id: str
    version_range: str = "*"


@dataclass(frozen=True)
class AgentPermissionSpec:
    tools: tuple[AgentToolPermission, ...] = ()
    skills: tuple[AgentSkillPermission, ...] = ()
    network: str = "none"


@dataclass(frozen=True)
class AgentEntrypoint:
    runtime: str
    ref: str


@dataclass(frozen=True)
class AgentManifest:
    schema_version: str
    kind: str
    id: str
    version: str
    host_api: str
    capabilities: tuple[AgentCapability, ...]
    io: AgentIOContract
    entrypoint: AgentEntrypoint
    permissions: AgentPermissionSpec = field(default_factory=AgentPermissionSpec)
    budgets: AgentBudgets = DEFAULT_AGENT_BUDGETS
    policy: dict[str, Any] = field(default_factory=dict)
    display_name: str | None = None
    description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentManifestValidationResult:
    valid: bool
    errors: list[str]
    manifest: AgentManifest | None = None


def validate_agent_manifest(raw: dict[str, Any]) -> AgentManifestValidationResult:
    errors: list[str] = []
    for key in ("schemaVersion", "kind", "id", "version", "hostApi", "capabilities", "io", "entrypoint"):
        if key not in raw:
            errors.append(f"{key} is required")

    schema_version = _string(raw.get("schemaVersion"))
    kind = _string(raw.get("kind"))
    agent_id = _string(raw.get("id"))
    version = _string(raw.get("version"))
    host_api = _string(raw.get("hostApi"))

    if kind and kind != "Agent":
        errors.append("kind must be Agent")
    if agent_id and not AGENT_ID_RE.match(agent_id):
        errors.append("id must use namespace/name kebab-case format")
    if version and not _is_semver(version):
        errors.append("version must be SemVer MAJOR.MINOR.PATCH")
    if host_api and not _is_supported_range(host_api):
        errors.append("hostApi must be a supported range expression")

    capabilities = _parse_capabilities(raw.get("capabilities"), errors)
    io = _parse_io(raw.get("io"), errors)
    permissions = _parse_permissions(raw.get("permissions", {}), errors)
    budgets = _parse_budgets(raw.get("budgets", {}), errors)
    entrypoint = _parse_entrypoint(raw.get("entrypoint"), errors)
    policy = raw.get("policy", {})
    if policy is not None and not isinstance(policy, dict):
        errors.append("policy must be an object when provided")
        policy = {}

    if errors:
        return AgentManifestValidationResult(False, errors)

    return AgentManifestValidationResult(
        True,
        [],
        AgentManifest(
            schema_version=schema_version,
            kind=kind,
            id=agent_id,
            version=version,
            host_api=host_api,
            capabilities=tuple(capabilities),
            io=io,
            permissions=permissions,
            budgets=budgets,
            policy=dict(policy or {}),
            entrypoint=entrypoint,
            display_name=_string(raw.get("displayName")) or None,
            description=_string(raw.get("description")) or None,
            raw=dict(raw),
        ),
    )


def load_agent_manifest(path: Path | str) -> AgentManifest:
    manifest_path = Path(path)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("agent.yaml must contain a mapping at the document root")
    resolved = _resolve_schema_refs(raw, manifest_path.parent)
    result = validate_agent_manifest(resolved)
    if not result.valid or result.manifest is None:
        raise ValueError("; ".join(result.errors))
    return result.manifest


def validate_agent_io(
    manifest: AgentManifest,
    payload: dict[str, Any],
    direction: Literal["input", "output"],
) -> dict[str, Any]:
    schema = manifest.io.input_schema if direction == "input" else manifest.io.output_schema
    _validate_schema(schema, payload, path="$")
    return payload


def _parse_capabilities(raw: Any, errors: list[str]) -> list[AgentCapability]:
    if not isinstance(raw, list) or not raw:
        errors.append("capabilities must contain at least one item")
        return []
    parsed: list[AgentCapability] = []
    for index, item in enumerate(raw):
        prefix = f"capabilities[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        capability_id = _string(item.get("id"))
        version = _string(item.get("version", "1.0.0"))
        level = _string(item.get("level", "primary"))
        if capability_id not in CAPABILITY_IDS:
            errors.append(f"unknown capability {capability_id}")
        if version and not _is_semver(version):
            errors.append(f"{prefix}.version must be SemVer MAJOR.MINOR.PATCH")
        if level not in VALID_LEVELS:
            errors.append(f"{prefix}.level must be primary or secondary")
        metadata = {k: v for k, v in item.items() if k not in {"id", "version", "level"}}
        parsed.append(AgentCapability(capability_id, version, level, metadata))
    return parsed


def _parse_io(raw: Any, errors: list[str]) -> AgentIOContract:
    if not isinstance(raw, dict):
        errors.append("io must be an object")
        return AgentIOContract("", "", {}, {})
    contract = _string(raw.get("contract"))
    contract_version = _string(raw.get("contractVersion"))
    on_invalid_output = _string(raw.get("onInvalidOutput", "fail"))
    input_schema = raw.get("input")
    output_schema = raw.get("output")
    if not contract or not CONTRACT_ID_RE.match(contract):
        errors.append("io.contract must use namespace/name kebab-case format")
    if not contract_version or not _is_semver(contract_version):
        errors.append("io.contractVersion must be SemVer MAJOR.MINOR.PATCH")
    if not isinstance(input_schema, dict):
        errors.append("io.input must be a JSON Schema object")
        input_schema = {}
    if not isinstance(output_schema, dict):
        errors.append("io.output must be a JSON Schema object")
        output_schema = {}
    if on_invalid_output not in VALID_INVALID_OUTPUT_ACTIONS:
        errors.append("io.onInvalidOutput must be repair-then-fail, fail, or passthrough")
    return AgentIOContract(contract, contract_version, dict(input_schema), dict(output_schema), on_invalid_output)


def _parse_permissions(raw: Any, errors: list[str]) -> AgentPermissionSpec:
    if raw is None:
        return AgentPermissionSpec()
    if not isinstance(raw, dict):
        errors.append("permissions must be an object")
        return AgentPermissionSpec()
    network = _string(raw.get("network", "none")) or "none"
    tools = []
    for item in raw.get("tools", []) or []:
        if isinstance(item, str):
            tools.append(AgentToolPermission(item))
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            constraints = item.get("constraints", {})
            tools.append(AgentToolPermission(item["id"], dict(constraints if isinstance(constraints, dict) else {})))
        else:
            errors.append("permissions.tools entries must be strings or objects with id")
    skills = []
    for item in raw.get("skills", []) or []:
        if isinstance(item, str):
            skills.append(AgentSkillPermission(item))
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            version_range = _string(item.get("versionRange", "*")) or "*"
            if version_range != "*" and not _is_supported_range(version_range):
                errors.append(f"permissions.skills[{item['id']}].versionRange must be a supported range expression")
            skills.append(AgentSkillPermission(item["id"], version_range))
        else:
            errors.append("permissions.skills entries must be strings or objects with id")
    return AgentPermissionSpec(tuple(tools), tuple(skills), network)


def _parse_budgets(raw: Any, errors: list[str]) -> AgentBudgets:
    if raw in (None, {}):
        return DEFAULT_AGENT_BUDGETS
    if not isinstance(raw, dict):
        errors.append("budgets must be an object")
        return DEFAULT_AGENT_BUDGETS
    tokens = raw.get("tokens", {})
    if tokens is not None and not isinstance(tokens, dict):
        errors.append("budgets.tokens must be an object")
        tokens = {}
    return AgentBudgets(
        tokens_input=_positive_int(tokens.get("input"), DEFAULT_AGENT_BUDGETS.tokens_input, "budgets.tokens.input", errors),
        tokens_output=_positive_int(tokens.get("output"), DEFAULT_AGENT_BUDGETS.tokens_output, "budgets.tokens.output", errors),
        cost_usd=_positive_float(raw.get("costUsd"), DEFAULT_AGENT_BUDGETS.cost_usd, "budgets.costUsd", errors),
        wall_clock_seconds=_positive_int(
            raw.get("wallClockSeconds"), DEFAULT_AGENT_BUDGETS.wall_clock_seconds, "budgets.wallClockSeconds", errors
        ),
        max_steps=_positive_int(raw.get("maxSteps"), DEFAULT_AGENT_BUDGETS.max_steps, "budgets.maxSteps", errors),
        max_tool_calls=_positive_int(
            raw.get("maxToolCalls"), DEFAULT_AGENT_BUDGETS.max_tool_calls, "budgets.maxToolCalls", errors
        ),
        on_exceeded=_string(raw.get("onExceeded", "fail-closed")) or "fail-closed",
    )


def _parse_entrypoint(raw: Any, errors: list[str]) -> AgentEntrypoint:
    if not isinstance(raw, dict):
        errors.append("entrypoint must be an object")
        return AgentEntrypoint("", "")
    runtime = _string(raw.get("runtime"))
    ref = _string(raw.get("ref"))
    if runtime != "python":
        errors.append("entrypoint.runtime must be python")
    if not ref or not ENTRYPOINT_REF_RE.match(ref):
        errors.append("entrypoint.ref must use module:callable format")
    return AgentEntrypoint(runtime, ref)


def _validate_schema(schema: dict[str, Any], value: Any, *, path: str) -> None:
    if "const" in schema and value != schema["const"]:
        raise ValidationError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{path} must be one of {schema['enum']!r}")
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise ValidationError(f"{path} must be an object")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ValidationError(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    raise ValidationError(f"{path}: additional property {key} is not allowed")
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                _validate_schema(child_schema, value[key], path=f"{path}.{key}")
    elif expected == "array":
        if not isinstance(value, list):
            raise ValidationError(f"{path} must be an array")
        item_schema = schema.get("items", {})
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_schema(item_schema, item, path=f"{path}[{index}]")
    elif expected == "string":
        if not isinstance(value, str):
            raise ValidationError(f"{path} must be a string")
        if len(value) < int(schema.get("minLength", 0)):
            raise ValidationError(f"{path} must not be empty")
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationError(f"{path} must be an integer")
    elif expected == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValidationError(f"{path} must be a number")
    elif expected == "boolean" and not isinstance(value, bool):
        raise ValidationError(f"{path} must be a boolean")


def _resolve_schema_refs(raw: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    resolved = dict(raw)
    io = resolved.get("io")
    if not isinstance(io, dict):
        return resolved
    io_copy = dict(io)
    for key in ("input", "output"):
        value = io_copy.get(key)
        if isinstance(value, dict) and isinstance(value.get("$ref"), str):
            ref = value["$ref"]
            if "://" in ref or not ref.startswith("./"):
                raise ValueError(f"io.{key} $ref must be a local relative path")
            schema_path = (base_dir / ref).resolve()
            if not _is_relative_to(schema_path, base_dir.resolve()):
                raise ValueError(f"io.{key} $ref must stay inside the agent directory")
            io_copy[key] = json.loads(schema_path.read_text(encoding="utf-8"))
    resolved["io"] = io_copy
    return resolved


def _is_semver(value: str) -> bool:
    if not SEMVER_RE.match(value):
        return False
    try:
        Version(value)
    except InvalidVersion:
        return False
    return True


def _is_supported_range(value: str) -> bool:
    if value == "*":
        return True
    try:
        SpecifierSet(value.replace(" ", ","))
    except InvalidSpecifier:
        return False
    return bool(value.strip())


def _positive_int(value: Any, default: int, field_name: str, errors: list[str]) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or value <= 0:
        errors.append(f"{field_name} must be a positive integer")
        return default
    return value


def _positive_float(value: Any, default: float, field_name: str, errors: list[str]) -> float:
    if value is None:
        return default
    if not isinstance(value, (int, float)) or value <= 0:
        errors.append(f"{field_name} must be a positive number")
        return default
    return float(value)


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


__all__ = [
    "AgentBudgets",
    "AgentCapability",
    "AgentEntrypoint",
    "AgentIOContract",
    "AgentManifest",
    "AgentManifestValidationResult",
    "AgentPermissionSpec",
    "AgentSkillPermission",
    "AgentToolPermission",
    "DEFAULT_AGENT_BUDGETS",
    "ValidationError",
    "load_agent_manifest",
    "validate_agent_io",
    "validate_agent_manifest",
]
