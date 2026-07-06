"""skill.yaml parsing and validation for the v2 Skill Registry.

Mirrors ``backend/plugins/manifest.py``'s parse/validate shape but for the
flatter skill permission model described in
``docs/architecture/v2_platform_reference.md`` Appendix D.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from backend.plugins.manifest import ENTRYPOINT_RE, PLUGIN_ID_RE, SEMVER_RE

SKILL_ID_RE = PLUGIN_ID_RE
FILESYSTEM_LEVELS = frozenset({"none", "read", "read-write"})
NETWORK_LEVELS = frozenset({"none", "allow"})
SKILL_KINDS = frozenset({"deterministic", "llm-assisted"})
_IO_TYPES = frozenset({"object", "string", "number", "boolean", "array"})


@dataclass(frozen=True)
class SkillIOSchema:
    """A typed IO contract for a skill's input or output.

    Attributes:
        schema_version: Schema version of this IO contract.
        type: JSON-Schema-like root type, e.g. ``"object"``.
        required: Required property names, when ``type`` is ``"object"``.
        properties: Property name to a small type descriptor dict.
    """

    schema_version: str
    type: str
    required: tuple[str, ...] = ()
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillPermissions:
    """Least-privilege permission declaration for a skill.

    Attributes:
        filesystem: One of ``"none"``, ``"read"``, ``"read-write"``.
        network: One of ``"none"`` or ``"allow"``.
        sandbox: Whether the skill requires the hardened execution sandbox.
    """

    filesystem: str = "none"
    network: str = "none"
    sandbox: bool = False


@dataclass(frozen=True)
class SkillDependency:
    """A dependency on another skill, resolved by SemVer in the Skill Registry.

    Attributes:
        id: Fully qualified id of the depended-on skill.
        version: SemVer range expression the dependency must satisfy.
    """

    id: str
    version: str


@dataclass(frozen=True)
class SkillBudgets:
    """Execution budgets enforced when a skill is invoked.

    Attributes:
        timeout_sec: Wall-clock timeout for a single invocation.
        max_cost_usd: Maximum cost, relevant when ``kind == "llm-assisted"``.
    """

    timeout_sec: float = 60.0
    max_cost_usd: float = 0.0


@dataclass(frozen=True)
class SkillManifest:
    """Fully parsed and validated ``skill.yaml`` manifest.

    Attributes:
        schema_version: Manifest schema version.
        id: Fully qualified skill id in ``namespace/name`` format.
        version: SemVer version of the skill.
        name: Human-readable name.
        description: Human-readable description.
        host_api: Supported host API version range.
        kind: ``"deterministic"`` or ``"llm-assisted"``.
        entrypoint: Module and callable reference, e.g. ``"pkg.module:run"``.
        io_input: Input IO contract.
        io_output: Output IO contract.
        permissions: Declared least-privilege permissions.
        dependencies: Other skills this skill depends on.
        triggers: Trigger identifiers that expose/suggest this skill.
        budgets: Execution budgets.
        raw: Original parsed manifest document.
    """

    schema_version: str
    id: str
    version: str
    name: str
    description: str
    host_api: str
    kind: str
    entrypoint: str
    io_input: SkillIOSchema
    io_output: SkillIOSchema
    permissions: SkillPermissions = field(default_factory=SkillPermissions)
    dependencies: tuple[SkillDependency, ...] = ()
    triggers: tuple[str, ...] = ()
    budgets: SkillBudgets = field(default_factory=SkillBudgets)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a raw skill manifest document.

    Attributes:
        valid: Whether the manifest passed validation.
        errors: Validation error messages, empty when ``valid`` is ``True``.
        manifest: The parsed manifest, present only when ``valid`` is ``True``.
    """

    valid: bool
    errors: list[str]
    manifest: SkillManifest | None = None


def validate_manifest(raw: dict[str, Any]) -> ValidationResult:
    """Validate a raw ``skill.yaml`` document and parse it into a :class:`SkillManifest`.

    Args:
        raw: Parsed ``skill.yaml`` document, keyed by camelCase field names.

    Returns:
        A result indicating whether the manifest is valid; on success it
        carries the parsed :class:`SkillManifest`, on failure the errors.
    """
    errors: list[str] = []
    for key in ("schemaVersion", "id", "version", "hostApi", "kind", "entrypoint", "io"):
        if key not in raw:
            errors.append(f"{key} is required")

    skill_id = _string(raw.get("id"))
    version = _string(raw.get("version"))
    host_api = _string(raw.get("hostApi"))
    schema_version = _string(raw.get("schemaVersion"))
    kind = _string(raw.get("kind"))
    entrypoint = _string(raw.get("entrypoint"))

    if skill_id and not SKILL_ID_RE.match(skill_id):
        errors.append("id must use namespace/name kebab-case format")
    if version and not _is_semver(version):
        errors.append("version must be SemVer MAJOR.MINOR.PATCH")
    if host_api and not _is_supported_range(host_api):
        errors.append("hostApi must be a supported range expression")
    if kind and kind not in SKILL_KINDS:
        errors.append("kind must be one of: deterministic, llm-assisted")
    if entrypoint and not ENTRYPOINT_RE.match(entrypoint):
        errors.append("entrypoint must use module:callable format")

    io_raw = raw.get("io") if isinstance(raw.get("io"), dict) else {}
    io_input = _parse_io_schema(io_raw.get("input"), "io.input", errors)
    io_output = _parse_io_schema(io_raw.get("output"), "io.output", errors)
    permissions = _parse_permissions(raw.get("permissions", {}), errors)
    dependencies = _parse_dependencies(raw.get("dependencies", []), errors)
    triggers = _string_list(raw.get("triggers", []), "triggers", errors)
    budgets = _parse_budgets(raw.get("budgets", {}), errors)

    if errors:
        return ValidationResult(valid=False, errors=errors)

    manifest = SkillManifest(
        schema_version=schema_version,
        id=skill_id,
        version=version,
        name=_string(raw.get("name")) or skill_id,
        description=_string(raw.get("description")),
        host_api=host_api,
        kind=kind,
        entrypoint=entrypoint,
        io_input=io_input,
        io_output=io_output,
        permissions=permissions,
        dependencies=tuple(dependencies),
        triggers=tuple(triggers),
        budgets=budgets,
        raw=dict(raw),
    )
    return ValidationResult(valid=True, errors=[], manifest=manifest)


def load_manifest(path: Path | str) -> SkillManifest:
    """Load and validate a ``skill.yaml`` manifest from disk.

    Args:
        path: Path to the ``skill.yaml`` file.

    Returns:
        The parsed and validated :class:`SkillManifest`.

    Raises:
        ValueError: If the document is not a mapping or fails validation.
    """
    manifest_path = Path(path)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("skill.yaml must contain a mapping at the document root")
    result = validate_manifest(raw)
    if not result.valid or result.manifest is None:
        raise ValueError("; ".join(result.errors))
    return result.manifest


def validate_io(schema: SkillIOSchema, payload: dict[str, Any]) -> list[str]:
    """Validate a payload against a skill IO contract.

    Deliberately lightweight (no external JSON-Schema dependency) so
    invocation-time validation stays well under the 20ms budget: it only
    checks required-key presence and the declared primitive ``type`` per
    property, rejecting keys not declared in ``properties``.

    Args:
        schema: The IO contract to validate against.
        payload: The candidate input or output payload.

    Returns:
        A list of validation error messages; empty when the payload is valid.
    """
    errors: list[str] = []
    if schema.type == "object":
        if not isinstance(payload, dict):
            return ["payload must be an object"]
        for key in schema.required:
            if key not in payload:
                errors.append(f"{key} is required")
        for key, value in payload.items():
            spec = schema.properties.get(key)
            if spec is None:
                errors.append(f"{key} is not declared in the IO schema")
                continue
            expected = spec.get("type")
            if expected and not _matches_type(value, expected):
                errors.append(f"{key} must be of type {expected}")
    return errors


def _is_semver(value: str) -> bool:
    """Check whether a string is a valid ``MAJOR.MINOR.PATCH`` SemVer version."""
    if not SEMVER_RE.match(value):
        return False
    try:
        Version(value)
    except InvalidVersion:
        return False
    return True


def _is_supported_range(value: str) -> bool:
    """Check whether a string is a valid, non-empty version range expression."""
    try:
        SpecifierSet(value.replace(" ", ","))
    except InvalidSpecifier:
        return False
    return bool(value.strip())


def _matches_type(value: Any, expected: str) -> bool:
    """Check whether ``value`` matches a small JSON-Schema-like primitive type name."""
    checks: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    py_type = checks.get(expected)
    if py_type is None:
        return True
    if expected == "number" and isinstance(value, bool):
        return False
    return isinstance(value, py_type)


def _string(value: Any) -> str:
    """Coerce a value to a string, defaulting to empty when not a string."""
    return value if isinstance(value, str) else ""


def _string_list(raw: Any, field_name: str, errors: list[str]) -> list[str]:
    """Validate and coerce a manifest field as a list of strings."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        errors.append(f"{field_name} must be a list of strings")
        return []
    return list(raw)


def _parse_io_schema(raw: Any, field_name: str, errors: list[str]) -> SkillIOSchema:
    """Parse and validate an ``io.input``/``io.output`` section."""
    if not isinstance(raw, dict):
        errors.append(f"{field_name} is required")
        return SkillIOSchema(schema_version="", type="object")
    schema_version = _string(raw.get("schemaVersion"))
    io_type = _string(raw.get("type"))
    if not schema_version:
        errors.append(f"{field_name}.schemaVersion is required")
    if io_type not in _IO_TYPES:
        errors.append(f"{field_name}.type must be one of: {', '.join(sorted(_IO_TYPES))}")
    required = _string_list(raw.get("required", []), f"{field_name}.required", errors)
    properties = raw.get("properties", {})
    if properties is not None and not isinstance(properties, dict):
        errors.append(f"{field_name}.properties must be an object")
        properties = {}
    return SkillIOSchema(
        schema_version=schema_version,
        type=io_type or "object",
        required=tuple(required),
        properties=dict(properties or {}),
    )


def _parse_permissions(raw: Any, errors: list[str]) -> SkillPermissions:
    """Parse and validate the ``permissions`` section of a raw manifest."""
    if raw is None:
        return SkillPermissions()
    if not isinstance(raw, dict):
        errors.append("permissions must be an object")
        return SkillPermissions()
    filesystem = _string(raw.get("filesystem", "none")) or "none"
    network = _string(raw.get("network", "none")) or "none"
    sandbox = raw.get("sandbox", False)
    if filesystem not in FILESYSTEM_LEVELS:
        errors.append("permissions.filesystem must be one of: none, read, read-write")
    if network not in NETWORK_LEVELS:
        errors.append("permissions.network must be one of: none, allow")
    if not isinstance(sandbox, bool):
        errors.append("permissions.sandbox must be a boolean")
        sandbox = False
    return SkillPermissions(filesystem=filesystem, network=network, sandbox=sandbox)


def _parse_dependencies(raw: Any, errors: list[str]) -> list[SkillDependency]:
    """Parse and validate the ``dependencies`` section of a raw manifest."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        errors.append("dependencies must be a list")
        return []
    parsed: list[SkillDependency] = []
    for index, item in enumerate(raw):
        prefix = f"dependencies[{index}]"
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("version"), str):
            errors.append(f"{prefix} must be an object with id and version")
            continue
        parsed.append(SkillDependency(id=item["id"], version=item["version"]))
    return parsed


def _parse_budgets(raw: Any, errors: list[str]) -> SkillBudgets:
    """Parse and validate the ``budgets`` section of a raw manifest."""
    if raw is None:
        return SkillBudgets()
    if not isinstance(raw, dict):
        errors.append("budgets must be an object")
        return SkillBudgets()
    timeout_sec = raw.get("timeoutSec", 60.0)
    max_cost_usd = raw.get("maxCostUsd", 0.0)
    if not isinstance(timeout_sec, (int, float)) or isinstance(timeout_sec, bool) or timeout_sec <= 0:
        errors.append("budgets.timeoutSec must be a positive number")
        timeout_sec = 60.0
    if not isinstance(max_cost_usd, (int, float)) or isinstance(max_cost_usd, bool) or max_cost_usd < 0:
        errors.append("budgets.maxCostUsd must be a non-negative number")
        max_cost_usd = 0.0
    return SkillBudgets(timeout_sec=float(timeout_sec), max_cost_usd=float(max_cost_usd))


__all__ = [
    "SKILL_ID_RE",
    "SkillBudgets",
    "SkillDependency",
    "SkillIOSchema",
    "SkillManifest",
    "SkillPermissions",
    "ValidationResult",
    "load_manifest",
    "validate_io",
    "validate_manifest",
]
