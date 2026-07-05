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
    """Resource limits enforced on a single agent run.

    Attributes:
        tokens_input: Maximum number of input tokens allowed.
        tokens_output: Maximum number of output tokens allowed.
        cost_usd: Maximum cost in US dollars allowed.
        wall_clock_seconds: Maximum wall-clock duration allowed, in seconds.
        max_steps: Maximum number of reasoning/execution steps allowed.
        max_tool_calls: Maximum number of tool invocations allowed.
        on_exceeded: Action to take when a budget is exceeded.
    """

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
    """A capability claimed by an agent manifest.

    Attributes:
        id: Dotted capability identifier declared in the manifest.
        version: SemVer version of the capability implementation.
        level: Whether this is the agent's ``"primary"`` or ``"secondary"`` capability.
        metadata: Additional capability-specific configuration.
    """

    id: str
    version: str
    level: str = "primary"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentIOContract:
    """Declared input/output contract for an agent.

    Attributes:
        contract: Contract identifier in ``namespace/name`` format.
        contract_version: SemVer version of the contract.
        input_schema: JSON Schema describing valid agent input.
        output_schema: JSON Schema describing valid agent output.
        on_invalid_output: Action to take when produced output fails validation.
    """

    contract: str
    contract_version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    on_invalid_output: str = "fail"


@dataclass(frozen=True)
class AgentToolPermission:
    """Grant of access to a single tool.

    Attributes:
        id: Identifier of the granted tool.
        constraints: Additional constraints scoping the grant.
    """

    id: str
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSkillPermission:
    """Grant of access to a single skill.

    Attributes:
        id: Identifier of the granted skill.
        version_range: SemVer range of skill versions covered by the grant.
    """

    id: str
    version_range: str = "*"


@dataclass(frozen=True)
class AgentPermissionSpec:
    """Aggregate permission grants for an agent.

    Attributes:
        tools: Tools the agent is granted access to.
        skills: Skills the agent is granted access to.
        network: Network access scope, e.g. ``"none"``.
    """

    tools: tuple[AgentToolPermission, ...] = ()
    skills: tuple[AgentSkillPermission, ...] = ()
    network: str = "none"


@dataclass(frozen=True)
class AgentEntrypoint:
    """Reference to the callable that implements an agent.

    Attributes:
        runtime: Runtime used to execute the entrypoint, e.g. ``"python"``.
        ref: Module and callable reference, e.g. ``"pkg.module:callable"``.
    """

    runtime: str
    ref: str


@dataclass(frozen=True)
class AgentManifest:
    """Fully parsed and validated ``agent.yaml`` manifest.

    Attributes:
        schema_version: Manifest schema version.
        kind: Manifest kind, always ``"Agent"``.
        id: Fully qualified agent id in ``namespace/name`` format.
        version: SemVer version of the agent.
        host_api: Supported host API version range.
        capabilities: Capabilities declared by the agent.
        io: Input/output contract declared by the agent.
        entrypoint: Reference to the agent's implementation.
        permissions: Tool, skill, and network grants for the agent.
        budgets: Resource limits enforced on the agent's runs.
        policy: Free-form policy configuration.
        display_name: Optional human-readable name.
        description: Optional human-readable description.
        raw: Original parsed manifest document.
    """

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
    """Outcome of validating a raw manifest document.

    Attributes:
        valid: Whether the manifest passed validation.
        errors: Validation error messages, empty when ``valid`` is ``True``.
        manifest: The parsed manifest, present only when ``valid`` is ``True``.
    """

    valid: bool
    errors: list[str]
    manifest: AgentManifest | None = None


def validate_agent_manifest(raw: dict[str, Any]) -> AgentManifestValidationResult:
    """Validate a raw manifest document and parse it into an :class:`AgentManifest`.

    Args:
        raw: Parsed ``agent.yaml`` document, keyed by camelCase field names.

    Returns:
        A result indicating whether the manifest is valid; on success it carries
        the parsed :class:`AgentManifest`, on failure the list of error messages.
    """
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
    """Load, resolve, and validate an ``agent.yaml`` manifest from disk.

    Args:
        path: Path to the ``agent.yaml`` file.

    Returns:
        The parsed and validated :class:`AgentManifest`.

    Raises:
        ValueError: If the document is not a mapping or fails validation.
    """
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
    """Validate a payload against an agent's declared input or output schema.

    Args:
        manifest: Agent manifest declaring the schema to validate against.
        payload: Payload to validate.
        direction: Whether to validate against the ``"input"`` or ``"output"`` schema.

    Returns:
        The payload, unchanged, if it satisfies the schema.

    Raises:
        ValidationError: If the payload violates the schema.
    """
    schema = manifest.io.input_schema if direction == "input" else manifest.io.output_schema
    _validate_schema(schema, payload, path="$")
    return payload


def _parse_capabilities(raw: Any, errors: list[str]) -> list[AgentCapability]:
    """Parse and validate the ``capabilities`` section of a raw manifest.

    Args:
        raw: Raw value of the ``capabilities`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed capabilities; empty if ``raw`` is not a non-empty list.
    """
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
    """Parse and validate the ``io`` section of a raw manifest.

    Args:
        raw: Raw value of the ``io`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed IO contract; empty schemas if ``raw`` is not an object.
    """
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
    """Parse and validate the ``permissions`` section of a raw manifest.

    Args:
        raw: Raw value of the ``permissions`` field, or ``None``.
        errors: Error list to append validation failures to.

    Returns:
        Parsed permission spec; defaults if ``raw`` is ``None`` or not an object.
    """
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
    """Parse and validate the ``budgets`` section of a raw manifest.

    Args:
        raw: Raw value of the ``budgets`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed budgets; :data:`DEFAULT_AGENT_BUDGETS` if ``raw`` is empty or not an object.
    """
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
    """Parse and validate the ``entrypoint`` section of a raw manifest.

    Args:
        raw: Raw value of the ``entrypoint`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed entrypoint; empty fields if ``raw`` is not an object.
    """
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
    """Recursively validate a value against a (subset of) JSON Schema.

    Args:
        schema: JSON Schema fragment to validate against.
        value: Value to validate.
        path: Human-readable path to ``value``, used in error messages.

    Raises:
        ValidationError: If ``value`` violates ``schema``.
    """
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
    """Resolve local ``$ref`` schema references in the ``io`` section.

    Args:
        raw: Raw manifest document.
        base_dir: Directory the manifest was loaded from, used to resolve relative refs.

    Returns:
        A copy of ``raw`` with any ``io.input``/``io.output`` ``$ref`` inlined.

    Raises:
        ValueError: If a ``$ref`` is not a local relative path inside ``base_dir``.
    """
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
    """Check whether a string is a valid ``MAJOR.MINOR.PATCH`` SemVer version.

    Args:
        value: Candidate version string.

    Returns:
        ``True`` if ``value`` is a valid SemVer version, ``False`` otherwise.
    """
    if not SEMVER_RE.match(value):
        return False
    try:
        Version(value)
    except InvalidVersion:
        return False
    return True


def _is_supported_range(value: str) -> bool:
    """Check whether a string is a valid version range expression.

    Args:
        value: Candidate range expression, or ``"*"`` for any version.

    Returns:
        ``True`` if ``value`` is ``"*"`` or a valid, non-empty specifier set.
    """
    if value == "*":
        return True
    try:
        SpecifierSet(value.replace(" ", ","))
    except InvalidSpecifier:
        return False
    return bool(value.strip())


def _positive_int(value: Any, default: int, field_name: str, errors: list[str]) -> int:
    """Coerce and validate a manifest field as a positive integer.

    Args:
        value: Raw field value, or ``None`` to use ``default``.
        default: Value to return when ``value`` is ``None`` or invalid.
        field_name: Dotted field name, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        ``value`` if it is a positive integer, otherwise ``default``.
    """
    if value is None:
        return default
    if not isinstance(value, int) or value <= 0:
        errors.append(f"{field_name} must be a positive integer")
        return default
    return value


def _positive_float(value: Any, default: float, field_name: str, errors: list[str]) -> float:
    """Coerce and validate a manifest field as a positive number.

    Args:
        value: Raw field value, or ``None`` to use ``default``.
        default: Value to return when ``value`` is ``None`` or invalid.
        field_name: Dotted field name, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        ``value`` as a ``float`` if it is a positive number, otherwise ``default``.
    """
    if value is None:
        return default
    if not isinstance(value, (int, float)) or value <= 0:
        errors.append(f"{field_name} must be a positive number")
        return default
    return float(value)


def _string(value: Any) -> str:
    """Coerce a value to a string, defaulting to empty when not a string.

    Args:
        value: Value to coerce.

    Returns:
        ``value`` if it is already a ``str``, otherwise an empty string.
    """
    return value if isinstance(value, str) else ""


def _is_relative_to(path: Path, root: Path) -> bool:
    """Check whether a path is contained within a root directory.

    Args:
        path: Path to check.
        root: Candidate root directory.

    Returns:
        ``True`` if ``path`` is ``root`` or a descendant of it.
    """
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
