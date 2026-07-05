"""Tests for the active plugin registry projection and its ``/v2/plugins/active`` API."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from backend.config.settings import reset_settings_cache
from backend.persistence.database import DurableStore, reset_store_cache
from backend.plugins.host import PluginHost, PluginState
from backend.plugins.registry import ActivePluginRegistry


def _write_plugin(root: Path, *, version: str = "0.1.0", body: str | None = None) -> Path:
    """Write (or overwrite) the ``registry-plugin`` project with an optional custom module body."""
    plugin_dir = root / "registry-plugin"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "registry_plugin.py").write_text(
        body
        or 'def register(host):\n    host.register_extension("skill", "acme/registry-plugin.skill", {"label": "v1"})\n',
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        textwrap.dedent(
            f"""
            schemaVersion: "1"
            id: "acme/registry-plugin"
            version: "{version}"
            hostApi: ">=2.0 <3.0"
            runtime:
              loader: "in-process"
              entrypoint: "registry_plugin:register"
            permissions: {{}}
            extensionPoints:
              - kind: "skill"
                id: "acme/registry-plugin.skill"
                contract: "^1.0"
            """
        ).strip(),
        encoding="utf-8",
    )
    return plugin_dir


@pytest.fixture()
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Point the process-wide store at an isolated temp database for the test's duration."""
    database_path = tmp_path / "plugins.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    reset_settings_cache()
    reset_store_cache()
    yield database_path
    reset_store_cache()
    reset_settings_cache()


def test_active_registry_is_consistent_after_enable_disable(tmp_path: Path) -> None:
    """The active-plugin snapshot reflects enable and disable transitions."""
    store = DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}")
    plugin_dir = _write_plugin(tmp_path)
    host = PluginHost(store=store)
    host.install(plugin_dir)
    host.enable("acme/registry-plugin")
    registry = ActivePluginRegistry(store)

    enabled_snapshot = registry.snapshot()

    assert enabled_snapshot["schemaVersion"] == "1"
    assert enabled_snapshot["activePlugins"][0]["id"] == "acme/registry-plugin"
    assert enabled_snapshot["inhabitedExtensionPoints"] == [
        {"kind": "skill", "pluginIds": ["acme/registry-plugin"]}
    ]

    host.disable("acme/registry-plugin")

    assert registry.snapshot()["activePlugins"] == []
    assert registry.snapshot()["inhabitedExtensionPoints"] == []


def test_v2_active_plugins_api_returns_schema_version(
    isolated_store: Path,
    tmp_path: Path,
) -> None:
    """The ``/v2/plugins/active`` endpoint returns the schema version and active plugins."""
    store = DurableStore(f"sqlite:///{isolated_store}")
    plugin_dir = _write_plugin(tmp_path)
    host = PluginHost(store=store)
    host.install(plugin_dir)
    host.enable("acme/registry-plugin")
    assert ActivePluginRegistry(store).snapshot()["activePlugins"][0]["id"] == "acme/registry-plugin"
    from backend.api.main import app
    from backend.api.routers.plugins import get_active_plugin_registry

    app.dependency_overrides[get_active_plugin_registry] = lambda: ActivePluginRegistry(store)
    try:
        response = TestClient(app).get("/v2/plugins/active")
    finally:
        app.dependency_overrides.pop(get_active_plugin_registry, None)


    assert response.status_code == 200
    payload = response.json()
    assert payload["schemaVersion"] == "1"
    assert payload["activePlugins"][0]["id"] == "acme/registry-plugin"


def test_dev_hot_reload_rolls_back_when_new_plugin_fails(tmp_path: Path) -> None:
    """A hot-reload whose new entrypoint raises rolls back to the previous version."""
    store = DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}")
    plugin_dir = _write_plugin(tmp_path)
    host = PluginHost(store=store)
    host.install(plugin_dir)
    host.enable("acme/registry-plugin")
    _write_plugin(
        tmp_path,
        version="0.2.0",
        body='def register(host):\n    raise RuntimeError("broken reload")\n',
    )

    record = host.hot_reload("acme/registry-plugin")

    assert record.state is PluginState.ENABLED
    assert record.version == "0.1.0"
    assert host.get("acme/registry-plugin").state is PluginState.ENABLED
