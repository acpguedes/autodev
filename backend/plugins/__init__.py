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

__all__ = [
    "EXTENSION_POINT_KINDS",
    "ExtensionPoint",
    "ExtensionPointKind",
    "PluginManifest",
    "ValidationResult",
    "get_extension_point",
    "load_manifest",
    "validate_manifest",
]
