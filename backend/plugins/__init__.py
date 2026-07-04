"""v2 plugin core contracts and host utilities."""

from backend.plugins.catalog import (
    EXTENSION_POINT_KINDS,
    ExtensionPoint,
    ExtensionPointKind,
    get_extension_point,
)
from backend.plugins.manifest import (
    PluginManifest,
    ValidationResult,
    load_manifest,
    validate_manifest,
)
from backend.plugins.host import PluginHost, PluginRecord, PluginState
from backend.plugins.permissions import PermissionBroker, PermissionDenied

__all__ = [
    "EXTENSION_POINT_KINDS",
    "ExtensionPoint",
    "ExtensionPointKind",
    "PermissionBroker",
    "PermissionDenied",
    "PluginHost",
    "PluginManifest",
    "PluginRecord",
    "PluginState",
    "ValidationResult",
    "get_extension_point",
    "load_manifest",
    "validate_manifest",
]
