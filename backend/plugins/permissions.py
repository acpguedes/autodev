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
    def __init__(self, plugin_id: str, capability: str, detail: str) -> None:
        self.plugin_id = plugin_id
        self.capability = capability
        self.detail = detail
        super().__init__(detail)


class PermissionBroker:
    def __init__(
        self,
        manifest: PluginManifest,
        *,
        workspace: Path,
        secrets: dict[str, str] | None = None,
        event_sink: Callable[[PluginEvent], None] | None = None,
    ) -> None:
        self.manifest = manifest
        self.workspace = workspace.resolve()
        self._secrets = secrets or {}
        self._event_sink = event_sink

    def read_text(self, path: Path | str) -> str:
        resolved = self._assert_path(path, self.manifest.permissions.filesystem_read, "filesystem.read")
        return resolved.read_text(encoding="utf-8")

    def write_text(self, path: Path | str, content: str) -> None:
        resolved = self._assert_path(path, self.manifest.permissions.filesystem_write, "filesystem.write")
        resolved.write_text(content, encoding="utf-8")

    def open_network(self, host: str, port: int) -> tuple[str, int]:
        target = f"{host}:{port}"
        if target not in self.manifest.permissions.network_egress:
            self._deny("network", f"network egress to {target} is not declared")
        return host, port

    def run_command(self, command: str) -> str:
        if command not in self.manifest.permissions.exec_commands:
            self._deny("exec", f"exec command {command!r} is not declared")
        return command

    def get_secret(self, name: str) -> str:
        if name not in self.manifest.permissions.secrets:
            self._deny("secrets", f"secret {name!r} is not declared")
        if name not in self._secrets:
            self._deny("secrets", f"secret {name!r} is not available")
        return self._secrets[name]

    @contextmanager
    def import_sandbox(self) -> Iterator[None]:
        original_import = builtins.__import__

        def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
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
        resolved = Path(path).expanduser().resolve()
        allowed_roots = [self._expand_path(grant) for grant in grants]
        if not any(self._is_relative_to(resolved, root) for root in allowed_roots):
            self._deny(capability, f"path {resolved} is outside declared {capability} grants")
        return resolved

    def _expand_path(self, grant: str) -> Path:
        return Path(grant.replace("${workspace}", str(self.workspace))).expanduser().resolve()

    def _deny(self, capability: str, detail: str) -> None:
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
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True


__all__ = ["PermissionBroker", "PermissionDenied"]
