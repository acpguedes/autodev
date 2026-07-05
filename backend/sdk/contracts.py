"""SemVer-stable Python contracts for plugin authors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from backend.agents.manifest import AgentManifest
from backend.flows.manifest import FlowManifest
from backend.plugins.catalog import ExtensionPointKind
from backend.plugins.manifest import PluginManifest

SDK_CONTRACT_VERSION = "1.1.0"


@dataclass(frozen=True)
class ExtensionRegistration:
    """A single extension a plugin registers at one of its declared extension points.

    Attributes:
        kind: Extension-point kind being registered.
        extension_id: Identifier of the extension.
        metadata: Extension-specific configuration.
    """

    kind: ExtensionPointKind
    extension_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContractTestResult:
    """Outcome of running a plugin's SDK contract tests.

    Attributes:
        passed: Whether the plugin satisfied the contract tests.
        plugin_id: Identifier of the tested plugin, if resolvable.
        errors: Failure messages, empty when ``passed`` is ``True``.
    """

    passed: bool
    plugin_id: str | None = None
    errors: tuple[str, ...] = ()


class HostApi(Protocol):
    """Structural interface for the host API exposed to an enabled plugin."""

    def register_extension(
        self,
        kind: str,
        extension_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register an extension the plugin provides at a declared extension point."""
        ...

    def read_text(self, path: Path | str) -> str:
        """Read a text file within the plugin's permitted filesystem scope."""
        ...

    def write_text(self, path: Path | str, content: str) -> None:
        """Write a text file within the plugin's permitted filesystem scope."""
        ...

    def open_network(self, host: str, port: int) -> tuple[str, int]:
        """Validate and return a network endpoint the plugin is permitted to reach."""
        ...

    def run_command(self, command: str) -> str:
        """Run a shell command within the plugin's permitted scope."""
        ...

    def get_secret(self, name: str) -> str:
        """Read a named secret the plugin is permitted to access."""
        ...


class PluginRegister(Protocol):
    """Structural interface for a plugin's registration entrypoint callable."""

    def __call__(self, host: HostApi) -> None:
        """Register the plugin's extensions against the given host API."""
        ...


class AgentHandler(Protocol):
    """Structural interface for an agent handler exposed by a plugin."""

    manifest: AgentManifest

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's logic for a single request."""
        ...


__all__ = [
    "ContractTestResult",
    "ExtensionRegistration",
    "AgentHandler",
    "AgentManifest",
    "FlowManifest",
    "HostApi",
    "PluginManifest",
    "PluginRegister",
    "SDK_CONTRACT_VERSION",
]
