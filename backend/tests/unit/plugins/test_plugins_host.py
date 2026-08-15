"""Tests for the plugin host: discovery, lifecycle state machine, and isolation."""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

import pytest

from backend.persistence.database import DurableStore
from backend.plugins.host import PluginHost, PluginState


def _write_plugin(
    root: Path,
    name: str,
    *,
    host_api: str = ">=2.0 <3.0",
    entrypoint: str | None = None,
    permissions_yaml: str = "",
    isolation: str | None = None,
) -> Path:
    """Write a minimal plugin project (module + manifest) under ``root``.

    Args:
        root: Directory the plugin project is created under.
        name: Plugin name; the plugin id becomes ``acme/<name>``.
        host_api: Declared ``hostApi`` SemVer range.
        entrypoint: Runtime entrypoint override.
        permissions_yaml: Raw YAML block substituted for ``permissions: {}``,
            indented to sit under the manifest's ``permissions:`` key.
        isolation: Optional ``runtime.isolation`` value.
    """
    plugin_dir = root / name
    plugin_dir.mkdir()
    module_name = name.replace("-", "_")
    (plugin_dir / f"{module_name}.py").write_text(
        "def register(host):\n"
        "    host.register_extension('skill', 'acme/%s.skill', {'ok': True})\n" % name,
        encoding="utf-8",
    )
    isolation_line = f'\n  isolation: "{isolation}"' if isolation else ""
    manifest = textwrap.dedent(
        f"""\
        schemaVersion: "1"
        id: "acme/{name}"
        version: "0.1.0"
        hostApi: "{host_api}"
        runtime:
          loader: "in-process"
          entrypoint: "{entrypoint or module_name + ':register'}"{isolation_line}
        """
    )
    if permissions_yaml:
        manifest += "permissions:\n" + textwrap.indent(permissions_yaml, "  ") + "\n"
    else:
        manifest += "permissions: {}\n"
    manifest += textwrap.dedent(
        f"""\
        extensionPoints:
          - kind: "skill"
            id: "acme/{name}.skill"
            contract: "^1.0"
        """
    )
    (plugin_dir / "plugin.yaml").write_text(manifest, encoding="utf-8")
    return plugin_dir


@pytest.fixture
def host(tmp_path: Path) -> PluginHost:
    """A fresh :class:`PluginHost` backed by a temp sqlite store and plugin directory."""
    store = DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}")
    return PluginHost(store=store, plugin_dirs=[tmp_path / "plugins"])


def test_directory_discovery_finds_plugin_manifests(host: PluginHost, tmp_path: Path) -> None:
    """Directory discovery finds a plugin's manifest and parses its id."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = _write_plugin(plugin_root, "example-plugin")

    discovered = host.discover()

    assert [candidate.path for candidate in discovered] == [plugin_dir]
    assert discovered[0].manifest.id == "acme/example-plugin"


def test_lifecycle_state_machine_emits_events(host: PluginHost, tmp_path: Path) -> None:
    """Install, enable, disable, and uninstall each transition state and emit an event."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = _write_plugin(plugin_root, "stateful-plugin")

    installed = host.install(plugin_dir)
    enabled = host.enable("acme/stateful-plugin")
    disabled = host.disable("acme/stateful-plugin")
    uninstalled = host.uninstall("acme/stateful-plugin")

    assert installed.state is PluginState.INSTALLED
    assert enabled.state is PluginState.ENABLED
    assert disabled.state is PluginState.DISABLED
    assert uninstalled.state is PluginState.UNINSTALLED
    assert [event.name for event in host.events] == [
        "plugin.installed",
        "plugin.enabled",
        "plugin.disabled",
    ]


def test_incompatible_host_api_is_rejected_with_reason(host: PluginHost, tmp_path: Path) -> None:
    """A plugin declaring an incompatible host API range is installed as rejected."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = _write_plugin(plugin_root, "future-plugin", host_api=">=3.0 <4.0")

    record = host.install(plugin_dir)

    assert record.state is PluginState.REJECTED
    assert "hostApi >=3.0 <4.0 is incompatible with host 2.0.0" in record.reason
    assert host.get("acme/future-plugin").state is PluginState.REJECTED


def test_broken_plugin_does_not_prevent_enabling_another(host: PluginHost, tmp_path: Path) -> None:
    """A plugin whose entrypoint fails to load is quarantined without blocking other plugins."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    broken_dir = _write_plugin(plugin_root, "broken-plugin", entrypoint="missing_module:register")
    good_dir = _write_plugin(plugin_root, "good-plugin")

    host.install(broken_dir)
    host.install(good_dir)

    broken = host.enable("acme/broken-plugin")
    good = host.enable("acme/good-plugin")

    assert broken.state is PluginState.QUARANTINED
    assert "No module named" in broken.reason
    assert good.state is PluginState.ENABLED


def test_discovering_50_plugins_stays_under_one_second(host: PluginHost, tmp_path: Path) -> None:
    """Discovery scales to 50 plugins while staying under a one-second budget."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    for index in range(50):
        _write_plugin(plugin_root, f"plugin-{index}")

    started = time.perf_counter()
    discovered = host.discover()
    elapsed = time.perf_counter() - started

    assert len(discovered) == 50
    assert elapsed < 1


def test_production_rejects_untrusted_in_process_plugin(
    tmp_path: Path,
) -> None:
    """An in-process plugin without an operator trust grant is rejected in production."""
    plugin_dir = _write_plugin(tmp_path, "untrusted-plugin")
    host = PluginHost(
        store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"),
        production_mode=True,
        trusted_in_process_plugins=(),
    )

    record = host.install(plugin_dir)

    assert record.state is PluginState.REJECTED
    assert record.reason == (
        "production requires an explicit operator trust grant for "
        "in-process plugin acme/untrusted-plugin"
    )


def test_production_rejects_privileged_trusted_in_process_plugin(
    tmp_path: Path,
) -> None:
    """A trusted in-process plugin requesting sensitive permissions is still rejected."""
    plugin_dir = _write_plugin(
        tmp_path,
        "network-plugin",
        permissions_yaml=("network:\n" "  egress:\n" "    - api.example.com:443"),
    )
    host = PluginHost(
        store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"),
        production_mode=True,
        trusted_in_process_plugins=("acme/network-plugin",),
    )

    record = host.install(plugin_dir)

    assert record.state is PluginState.REJECTED
    assert "permissions.network.egress" in record.reason


def test_production_accepts_explicitly_trusted_unprivileged_plugin(
    tmp_path: Path,
) -> None:
    """An explicitly trusted, unprivileged in-process plugin installs in production."""
    plugin_dir = _write_plugin(tmp_path, "trusted-plugin")
    host = PluginHost(
        store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"),
        production_mode=True,
        trusted_in_process_plugins=("acme/trusted-plugin",),
    )

    assert host.install(plugin_dir).state is PluginState.INSTALLED


def test_local_mode_preserves_current_in_process_behavior(
    tmp_path: Path,
) -> None:
    """Local (non-production) mode installs in-process plugins without a trust grant."""
    plugin_dir = _write_plugin(
        tmp_path,
        "local-plugin",
        permissions_yaml=("filesystem:\n" "  read:\n" "    - ${workspace}"),
    )
    host = PluginHost(
        store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"),
        production_mode=False,
        trusted_in_process_plugins=(),
    )

    assert host.install(plugin_dir).state is PluginState.INSTALLED
