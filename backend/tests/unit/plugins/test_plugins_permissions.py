"""Tests for the plugin permission broker: filesystem, network, exec, and secret grants."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.persistence.database import DurableStore
from backend.plugins.host import PluginHost, PluginState
from backend.plugins.permissions import PermissionBroker, PermissionDenied


def _manifest(
    plugin_id: str,
    *,
    entrypoint: str = "safe_plugin:register",
    permissions: str = "{}",
) -> str:
    """Render a minimal ``plugin.yaml`` document with a given permissions block."""
    permissions_yaml = textwrap.indent(permissions, "  ") if permissions != "{}" else "  {}"
    return "\n".join(
        [
            'schemaVersion: "1"',
            f'id: "{plugin_id}"',
            'version: "0.1.0"',
            'hostApi: ">=2.0 <3.0"',
            "runtime:",
            '  loader: "in-process"',
            f'  entrypoint: "{entrypoint}"',
            "permissions:",
            permissions_yaml,
            "extensionPoints:",
            '  - kind: "skill"',
            f'    id: "{plugin_id}.skill"',
            '    contract: "^1.0"',
        ]
    )


def _write_plugin(tmp_path: Path, plugin_id: str, module: str, manifest: str) -> Path:
    """Write a plugin project with a given module body and manifest content."""
    plugin_dir = tmp_path / plugin_id.split("/", 1)[1]
    plugin_dir.mkdir()
    (plugin_dir / "safe_plugin.py").write_text(module, encoding="utf-8")
    (plugin_dir / "plugin.yaml").write_text(manifest, encoding="utf-8")
    return plugin_dir


def test_permission_broker_default_denies_all_capabilities(tmp_path: Path) -> None:
    """With no grants declared, every capability is denied and audited."""
    plugin_dir = _write_plugin(
        tmp_path,
        "acme/default-deny",
        "def register(host): pass\n",
        _manifest("acme/default-deny"),
    )
    host = PluginHost(store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"))
    record = host.install(plugin_dir)
    broker = PermissionBroker(record.manifest, workspace=tmp_path, event_sink=host.audit_permission_denial)

    with pytest.raises(PermissionDenied):
        broker.read_text(tmp_path / "data.txt")
    with pytest.raises(PermissionDenied):
        broker.open_network("example.com", 443)
    with pytest.raises(PermissionDenied):
        broker.run_command("pytest")
    with pytest.raises(PermissionDenied):
        broker.get_secret("TOKEN")

    assert [event.name for event in host.events] == [
        "plugin.installed",
        "plugin.permission.denied",
        "plugin.permission.denied",
        "plugin.permission.denied",
        "plugin.permission.denied",
    ]


def test_permission_broker_allows_declared_filesystem_paths(tmp_path: Path) -> None:
    """Read/write within a declared filesystem grant succeeds; outside it is denied."""
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    (allowed / "input.txt").write_text("ok", encoding="utf-8")
    (denied / "input.txt").write_text("nope", encoding="utf-8")
    plugin_dir = _write_plugin(
        tmp_path,
        "acme/fs-plugin",
        "def register(host): pass\n",
        _manifest(
            "acme/fs-plugin",
            permissions=f"""
filesystem:
  read:
    - "{allowed}"
  write:
    - "{allowed}"
""".strip(),
        ),
    )
    host = PluginHost(store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"))
    record = host.install(plugin_dir)
    broker = PermissionBroker(record.manifest, workspace=tmp_path, event_sink=host.audit_permission_denial)

    assert broker.read_text(allowed / "input.txt") == "ok"
    broker.write_text(allowed / "output.txt", "written")
    with pytest.raises(PermissionDenied):
        broker.read_text(denied / "input.txt")

    assert (allowed / "output.txt").read_text(encoding="utf-8") == "written"


def test_declared_network_exec_and_secret_grants_are_available(tmp_path: Path) -> None:
    """Declared network, exec, and secret grants are usable through the broker."""
    plugin_dir = _write_plugin(
        tmp_path,
        "acme/capability-plugin",
        "def register(host): pass\n",
        _manifest(
            "acme/capability-plugin",
            permissions="""
network:
  egress:
    - "api.example.com:443"
exec:
  commands:
    - "pytest"
secrets:
  - name: TOKEN
    required: true
""".strip(),
        ),
    )
    host = PluginHost(store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"))
    record = host.install(plugin_dir)
    broker = PermissionBroker(
        record.manifest,
        workspace=tmp_path,
        secrets={"TOKEN": "value"},
        event_sink=host.audit_permission_denial,
    )

    assert broker.open_network("api.example.com", 443) == ("api.example.com", 443)
    assert broker.run_command("pytest") == "pytest"
    assert broker.get_secret("TOKEN") == "value"


def test_import_sandbox_blocks_undeclared_network_import_and_audits(tmp_path: Path) -> None:
    """Importing a network module without a declared egress grant quarantines the plugin."""
    plugin_dir = _write_plugin(
        tmp_path,
        "acme/unsafe-plugin",
        "def register(host):\n    import socket\n    socket.socket()\n",
        _manifest("acme/unsafe-plugin"),
    )
    host = PluginHost(store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"))
    host.install(plugin_dir)

    record = host.enable("acme/unsafe-plugin")

    assert record.state is PluginState.QUARANTINED
    assert "network imports require permissions.network.egress" in record.reason
    assert host.events[-1].name == "plugin.permission.denied"
    assert host.events[-1].payload["capability"] == "network"
