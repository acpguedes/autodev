"""plugin.yaml parsing and validation for the v2 Plugin Host."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from backend.plugins.catalog import ExtensionPointKind

PLUGIN_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")
EXTENSION_ID_RE = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+$"
)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
ENTRYPOINT_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_][\w.]*$")
PERMISSION_KEYS = frozenset({"hostApi", "network", "filesystem", "exec", "secrets", "events"})
RUNTIME_LOADERS = frozenset({"in-process", "subprocess", "wasm"})


@dataclass(frozen=True)
class RuntimeSpec:
    """How a plugin's entrypoint is loaded and isolated.

    Attributes:
        loader: Loader mechanism, one of :data:`RUNTIME_LOADERS`.
        entrypoint: Module and callable reference, e.g. ``"pkg.module:register"``.
        isolation: Optional isolation strategy for the loader.
        resources: Loader-specific resource configuration.
    """

    loader: str
    entrypoint: str
    isolation: str | None = None
    resources: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PermissionSpec:
    """Permission grants declared by a plugin manifest.

    Attributes:
        host_api: Host API version ranges the plugin declares support for.
        network_egress: Allowed network egress destinations.
        filesystem_read: Allowed filesystem read paths.
        filesystem_write: Allowed filesystem write paths.
        exec_commands: Allowed shell commands.
        secrets: Allowed secret names.
        events_publish: Event names the plugin may publish.
        events_subscribe: Event names the plugin may subscribe to.
    """

    host_api: tuple[str, ...] = ()
    network_egress: tuple[str, ...] = ()
    filesystem_read: tuple[str, ...] = ()
    filesystem_write: tuple[str, ...] = ()
    exec_commands: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    events_publish: tuple[str, ...] = ()
    events_subscribe: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManifestExtensionPoint:
    """A single extension point declared by a plugin manifest.

    Attributes:
        kind: Canonical extension-point kind.
        id: Identifier of the extension within the plugin.
        contract: Contract version range the extension implements.
        entrypoint: Optional module:callable reference for this extension.
        manifest: Optional path to a nested manifest (e.g. an agent manifest).
        metadata: Additional extension-specific configuration.
    """

    kind: ExtensionPointKind
    id: str
    contract: str
    entrypoint: str | None = None
    manifest: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginManifest:
    """Fully parsed and validated ``plugin.yaml`` manifest.

    Attributes:
        schema_version: Manifest schema version.
        id: Fully qualified plugin id in ``namespace/name`` format.
        version: SemVer version of the plugin.
        host_api: Supported host API version range.
        runtime: How the plugin's entrypoint is loaded.
        extension_points: Extension points the plugin declares.
        permissions: Permission grants declared by the plugin.
        name: Optional human-readable name.
        description: Optional human-readable description.
        raw: Original parsed manifest document.
    """

    schema_version: str
    id: str
    version: str
    host_api: str
    runtime: RuntimeSpec
    extension_points: tuple[ManifestExtensionPoint, ...]
    permissions: PermissionSpec = field(default_factory=PermissionSpec)
    name: str | None = None
    description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a raw plugin manifest document.

    Attributes:
        valid: Whether the manifest passed validation.
        errors: Validation error messages, empty when ``valid`` is ``True``.
        manifest: The parsed manifest, present only when ``valid`` is ``True``.
    """

    valid: bool
    errors: list[str]
    manifest: PluginManifest | None = None


def validate_manifest(raw: dict[str, Any]) -> ValidationResult:
    """Validate a raw manifest document and parse it into a :class:`PluginManifest`.

    Args:
        raw: Parsed ``plugin.yaml`` document, keyed by camelCase field names.

    Returns:
        A result indicating whether the manifest is valid; on success it
        carries the parsed :class:`PluginManifest`, on failure the errors.
    """
    errors: list[str] = []
    _require(raw, "schemaVersion", errors)
    _require(raw, "id", errors)
    _require(raw, "version", errors)
    _require(raw, "hostApi", errors)
    _require(raw, "runtime", errors)
    _require(raw, "extensionPoints", errors)

    plugin_id = _string(raw.get("id"))
    version = _string(raw.get("version"))
    host_api = _string(raw.get("hostApi"))
    schema_version = _string(raw.get("schemaVersion"))

    if plugin_id and not PLUGIN_ID_RE.match(plugin_id):
        errors.append("id must use namespace/name kebab-case format")
    if version and not _is_semver(version):
        errors.append("version must be SemVer MAJOR.MINOR.PATCH")
    if host_api and not _is_supported_range(host_api):
        errors.append("hostApi must be a supported range expression")

    runtime = _parse_runtime(raw.get("runtime"), errors)
    permissions = _parse_permissions(raw.get("permissions", {}), errors)
    extension_points = _parse_extension_points(raw.get("extensionPoints"), errors)

    if errors:
        return ValidationResult(valid=False, errors=errors)

    manifest = PluginManifest(
        schema_version=schema_version,
        id=plugin_id,
        version=version,
        host_api=host_api,
        runtime=runtime,
        permissions=permissions,
        extension_points=tuple(extension_points),
        name=_string(raw.get("name")) or None,
        description=_string(raw.get("description")) or None,
        raw=dict(raw),
    )
    return ValidationResult(valid=True, errors=[], manifest=manifest)


def load_manifest(path: Path | str) -> PluginManifest:
    """Load and validate a ``plugin.yaml`` manifest from disk.

    Args:
        path: Path to the ``plugin.yaml`` file.

    Returns:
        The parsed and validated :class:`PluginManifest`.

    Raises:
        ValueError: If the document is not a mapping or fails validation.
    """
    manifest_path = Path(path)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("plugin.yaml must contain a mapping at the document root")
    result = validate_manifest(raw)
    if not result.valid or result.manifest is None:
        raise ValueError("; ".join(result.errors))
    return result.manifest


def _require(raw: dict[str, Any], key: str, errors: list[str]) -> None:
    """Append an error if ``key`` is missing from ``raw``."""
    if key not in raw:
        errors.append(f"{key} is required")


def _string(value: Any) -> str:
    """Coerce a value to a string, defaulting to empty when not a string."""
    return value if isinstance(value, str) else ""


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


def _parse_runtime(raw: Any, errors: list[str]) -> RuntimeSpec:
    """Parse and validate the ``runtime`` section of a raw manifest."""
    if not isinstance(raw, dict):
        errors.append("runtime must be an object with loader and entrypoint")
        return RuntimeSpec(loader="", entrypoint="")
    loader = _string(raw.get("loader"))
    entrypoint = _string(raw.get("entrypoint"))
    if not loader:
        errors.append("runtime.loader is required")
    elif loader not in RUNTIME_LOADERS:
        errors.append("runtime.loader must be one of: in-process, subprocess, wasm")
    if not entrypoint:
        errors.append("runtime.entrypoint is required")
    elif not ENTRYPOINT_RE.match(entrypoint):
        errors.append("runtime.entrypoint must use module:callable format")
    resources = raw.get("resources", {})
    if resources is not None and not isinstance(resources, dict):
        errors.append("runtime.resources must be an object when provided")
        resources = {}
    return RuntimeSpec(
        loader=loader,
        entrypoint=entrypoint,
        isolation=_string(raw.get("isolation")) or None,
        resources=dict(resources or {}),
    )


def _parse_permissions(raw: Any, errors: list[str]) -> PermissionSpec:
    """Parse and validate the ``permissions`` section of a raw manifest."""
    if raw is None:
        return PermissionSpec()
    if not isinstance(raw, dict):
        errors.append("permissions must be an object")
        return PermissionSpec()
    unknown = sorted(set(raw) - PERMISSION_KEYS)
    if unknown:
        errors.append(f"unknown permission block(s): {', '.join(unknown)}")

    host_api = _string_list(raw.get("hostApi", []), "permissions.hostApi", errors)
    network = raw.get("network", {})
    filesystem = raw.get("filesystem", {})
    exec_block = raw.get("exec", {})
    events = raw.get("events", {})
    return PermissionSpec(
        host_api=tuple(host_api),
        network_egress=tuple(_nested_string_list(network, "egress", "permissions.network.egress", errors)),
        filesystem_read=tuple(_nested_string_list(filesystem, "read", "permissions.filesystem.read", errors)),
        filesystem_write=tuple(_nested_string_list(filesystem, "write", "permissions.filesystem.write", errors)),
        exec_commands=tuple(_nested_string_list(exec_block, "commands", "permissions.exec.commands", errors)),
        secrets=tuple(_parse_secrets(raw.get("secrets", []), errors)),
        events_publish=tuple(_nested_string_list(events, "publish", "permissions.events.publish", errors)),
        events_subscribe=tuple(_nested_string_list(events, "subscribe", "permissions.events.subscribe", errors)),
    )


def _parse_extension_points(raw: Any, errors: list[str]) -> list[ManifestExtensionPoint]:
    """Parse and validate the ``extensionPoints`` section of a raw manifest."""
    if not isinstance(raw, list) or not raw:
        errors.append("extensionPoints must contain at least one item")
        return []
    parsed: list[ManifestExtensionPoint] = []
    for index, item in enumerate(raw):
        prefix = f"extensionPoints[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        kind_raw = _string(item.get("kind") or item.get("type"))
        if not kind_raw:
            errors.append(f"{prefix}.kind is required")
            continue
        try:
            kind = ExtensionPointKind(kind_raw.replace("-", "_"))
        except ValueError:
            errors.append(f"unknown extension point kind {kind_raw!r}")
            continue
        point_id = _string(item.get("id"))
        contract = _string(item.get("contract", "^1.0"))
        entrypoint = _string(item.get("entrypoint")) or None
        if not point_id or not EXTENSION_ID_RE.match(point_id):
            errors.append(f"{prefix}.id must use namespace/name.detail kebab-case format")
        if not contract:
            errors.append(f"{prefix}.contract is required")
        if entrypoint is not None and not ENTRYPOINT_RE.match(entrypoint):
            errors.append(f"{prefix}.entrypoint must use module:callable format")
        metadata = {k: v for k, v in item.items() if k not in {"kind", "type", "id", "contract", "entrypoint", "manifest"}}
        parsed.append(
            ManifestExtensionPoint(
                kind=kind,
                id=point_id,
                contract=contract,
                entrypoint=entrypoint,
                manifest=_string(item.get("manifest")) or None,
                metadata=metadata,
            )
        )
    return parsed


def _string_list(raw: Any, field_name: str, errors: list[str]) -> list[str]:
    """Validate and coerce a manifest field as a list of strings.

    Args:
        raw: Raw field value.
        field_name: Dotted field name, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        The list of strings; empty if ``raw`` is unset or invalid.
    """
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        errors.append(f"{field_name} must be a list of strings")
        return []
    return list(raw)


def _nested_string_list(raw: Any, key: str, field_name: str, errors: list[str]) -> list[str]:
    """Validate and coerce a nested manifest field as a list of strings.

    Args:
        raw: Raw value of the parent object (e.g. ``permissions.network``).
        key: Key within ``raw`` holding the list of strings.
        field_name: Dotted field name, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        The list of strings; empty if ``raw`` is unset or invalid.
    """
    if raw in (None, {}):
        return []
    if not isinstance(raw, dict):
        errors.append(f"{field_name.rsplit('.', 1)[0]} must be an object")
        return []
    return _string_list(raw.get(key, []), field_name, errors)


def _parse_secrets(raw: Any, errors: list[str]) -> list[str]:
    """Parse and validate the ``permissions.secrets`` section of a raw manifest."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        errors.append("permissions.secrets must be a list")
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
        else:
            errors.append("permissions.secrets entries must be strings or objects with name")
    return names


__all__ = [
    "ManifestExtensionPoint",
    "PermissionSpec",
    "PluginManifest",
    "RuntimeSpec",
    "ValidationResult",
    "load_manifest",
    "validate_manifest",
]
