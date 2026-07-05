"""Least-privilege permission broker for plugin execution."""

from __future__ import annotations

import builtins
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.plugins.events import PluginEvent
from backend.plugins.manifest import PluginManifest

NETWORK_MODULES = frozenset({"socket", "http.client", "urllib", "urllib3", "requests"})
EXEC_MODULES = frozenset({"subprocess", "pty"})
SECRET_MODULES = frozenset({"keyring"})


class PermissionDenied(PermissionError):
    """Raised when a plugin attempts an action outside its declared permissions.

    Attributes:
        plugin_id: Identifier of the plugin that was denied.
        capability: Capability category that was denied (e.g. ``"network"``).
        detail: Human-readable denial reason.
    """

    def __init__(self, plugin_id: str, capability: str, detail: str) -> None:
        """Initialize the exception with the denied plugin, capability, and reason.

        Args:
            plugin_id: Identifier of the plugin that was denied.
            capability: Capability category that was denied.
            detail: Human-readable denial reason.
        """
        self.plugin_id = plugin_id
        self.capability = capability
        self.detail = detail
        super().__init__(detail)


class PermissionBroker:
    """Enforces a plugin's declared filesystem, network, exec, and secret permissions."""

    def __init__(
        self,
        manifest: PluginManifest,
        *,
        workspace: Path,
        secrets: dict[str, str] | None = None,
        event_sink: Callable[[PluginEvent], None] | None = None,
    ) -> None:
        """Initialize the broker for a single plugin manifest.

        Args:
            manifest: Manifest describing the plugin's granted permissions.
            workspace: Root directory used to resolve ``${workspace}`` grants.
            secrets: Secrets available to the plugin, keyed by name.
            event_sink: Callback invoked with a :class:`PluginEvent` on every denial.
        """
        self.manifest = manifest
        self.workspace = workspace.resolve()
        self._secrets = secrets or {}
        self._event_sink = event_sink

    def read_text(self, path: Path | str) -> str:
        """Read a text file if it falls within a declared filesystem-read grant.

        Raises:
            PermissionDenied: If ``path`` is outside the plugin's read grants.
        """
        resolved = self._assert_path(path, self.manifest.permissions.filesystem_read, "filesystem.read")
        return resolved.read_text(encoding="utf-8")

    def write_text(self, path: Path | str, content: str) -> None:
        """Write a text file if it falls within a declared filesystem-write grant.

        Raises:
            PermissionDenied: If ``path`` is outside the plugin's write grants.
        """
        resolved = self._assert_path(path, self.manifest.permissions.filesystem_write, "filesystem.write")
        resolved.write_text(content, encoding="utf-8")

    def open_network(self, host: str, port: int) -> tuple[str, int]:
        """Validate and return a network endpoint the plugin is permitted to reach.

        Raises:
            PermissionDenied: If ``host:port`` is not a declared network-egress grant.
        """
        target = f"{host}:{port}"
        if target not in self.manifest.permissions.network_egress:
            self._deny("network", f"network egress to {target} is not declared")
        return host, port

    def run_command(self, command: str) -> str:
        """Validate and return a shell command the plugin is permitted to run.

        Raises:
            PermissionDenied: If ``command`` is not a declared exec-command grant.
        """
        if command not in self.manifest.permissions.exec_commands:
            self._deny("exec", f"exec command {command!r} is not declared")
        return command

    def get_secret(self, name: str) -> str:
        """Read a named secret if the plugin declares and has access to it.

        Raises:
            PermissionDenied: If ``name`` is not declared or not available.
        """
        if name not in self.manifest.permissions.secrets:
            self._deny("secrets", f"secret {name!r} is not declared")
        if name not in self._secrets:
            self._deny("secrets", f"secret {name!r} is not available")
        return self._secrets[name]

    @contextmanager
    def import_sandbox(self) -> Iterator[None]:
        """Guard imports of network/exec/secret-adjacent modules for the plugin's code.

        Yields:
            Control to the sandboxed block, with ``builtins.__import__`` patched.
        """
        original_import = builtins.__import__

        def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
            """Deny imports of privileged modules the plugin has no matching grant for."""
            root = name.split(".", 1)[0]
            if root in NETWORK_MODULES and not self.manifest.permissions.network_egress:
                self._deny("network", "network imports require permissions.network.egress")
            if root in EXEC_MODULES and not self.manifest.permissions.exec_commands:
                self._deny("exec", "exec imports require permissions.exec.commands")
            if root in SECRET_MODULES and not self.manifest.permissions.secrets:
                self._deny("secrets", "secret imports require permissions.secrets")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = guarded_import
        try:
            yield
        finally:
            builtins.__import__ = original_import

    def _assert_path(self, path: Path | str, grants: tuple[str, ...], capability: str) -> Path:
        """Resolve a path and verify it falls under one of the given grants.

        Raises:
            PermissionDenied: If ``path`` is outside every grant in ``grants``.
        """
        resolved = Path(path).expanduser().resolve()
        allowed_roots = [self._expand_path(grant) for grant in grants]
        if not any(self._is_relative_to(resolved, root) for root in allowed_roots):
            self._deny(capability, f"path {resolved} is outside declared {capability} grants")
        return resolved

    def _expand_path(self, grant: str) -> Path:
        """Expand a ``${workspace}``-templated grant into an absolute path."""
        return Path(grant.replace("${workspace}", str(self.workspace))).expanduser().resolve()

    def _deny(self, capability: str, detail: str) -> None:
        """Emit a denial event (if configured) and raise :class:`PermissionDenied`.

        Raises:
            PermissionDenied: Always.
        """
        event = PluginEvent(
            name="plugin.permission.denied",
            plugin_id=self.manifest.id,
            payload={"capability": capability, "detail": detail},
        )
        if self._event_sink is not None:
            self._event_sink(event)
        raise PermissionDenied(self.manifest.id, capability, detail)

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        """Check whether a path is contained within a root directory."""
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True


__all__ = ["PermissionBroker", "PermissionDenied"]
