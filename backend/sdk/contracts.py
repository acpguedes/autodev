"""SemVer-stable Python contracts for plugin authors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from backend.agents.manifest import AgentManifest
from backend.plugins.catalog import ExtensionPointKind
from backend.plugins.manifest import PluginManifest

SDK_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class ExtensionRegistration:
    kind: ExtensionPointKind
    extension_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContractTestResult:
    passed: bool
    plugin_id: str | None = None
    errors: tuple[str, ...] = ()


class HostApi(Protocol):
    def register_extension(
        self,
        kind: str,
        extension_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def read_text(self, path: Path | str) -> str: ...

    def write_text(self, path: Path | str, content: str) -> None: ...

    def open_network(self, host: str, port: int) -> tuple[str, int]: ...

    def run_command(self, command: str) -> str: ...

    def get_secret(self, name: str) -> str: ...


class PluginRegister(Protocol):
    def __call__(self, host: HostApi) -> None: ...


class AgentHandler(Protocol):
    manifest: AgentManifest

    def run(self, request: dict[str, Any]) -> dict[str, Any]: ...


__all__ = [
    "ContractTestResult",
    "ExtensionRegistration",
    "AgentHandler",
    "AgentManifest",
    "HostApi",
    "PluginManifest",
    "PluginRegister",
    "SDK_CONTRACT_VERSION",
]
