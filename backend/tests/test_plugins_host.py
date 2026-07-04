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
) -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir()
    module_name = name.replace("-", "_")
    (plugin_dir / f"{module_name}.py").write_text(
        "def register(host):\n"
        "    host.register_extension('skill', 'acme/%s.skill', {'ok': True})\n" % name,
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        textwrap.dedent(
            f"""
            schemaVersion: "1"
            id: "acme/{name}"
            version: "0.1.0"
            hostApi: "{host_api}"
            runtime:
              loader: "in-process"
              entrypoint: "{entrypoint or module_name + ':register'}"
            permissions: {{}}
            extensionPoints:
              - kind: "skill"
                id: "acme/{name}.skill"
                contract: "^1.0"
            """
        ).strip(),
        encoding="utf-8",
    )
    return plugin_dir


@pytest.fixture
def host(tmp_path: Path) -> PluginHost:
    store = DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}")
    return PluginHost(store=store, plugin_dirs=[tmp_path / "plugins"])


def test_directory_discovery_finds_plugin_manifests(host: PluginHost, tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = _write_plugin(plugin_root, "example-plugin")

    discovered = host.discover()

    assert [candidate.path for candidate in discovered] == [plugin_dir]
    assert discovered[0].manifest.id == "acme/example-plugin"


def test_lifecycle_state_machine_emits_events(host: PluginHost, tmp_path: Path) -> None:
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
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = _write_plugin(plugin_root, "future-plugin", host_api=">=3.0 <4.0")

    record = host.install(plugin_dir)

    assert record.state is PluginState.REJECTED
    assert "hostApi >=3.0 <4.0 is incompatible with host 2.0.0" in record.reason
    assert host.get("acme/future-plugin").state is PluginState.REJECTED


def test_broken_plugin_does_not_prevent_enabling_another(host: PluginHost, tmp_path: Path) -> None:
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
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    for index in range(50):
        _write_plugin(plugin_root, f"plugin-{index}")

    started = time.perf_counter()
    discovered = host.discover()
    elapsed = time.perf_counter() - started

    assert len(discovered) == 50
    assert elapsed < 1
