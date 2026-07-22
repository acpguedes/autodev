"""Contract test for ``hostApi`` SemVer compatibility (E12-S2-T2).

Exercises the real install-time compatibility gate --
:class:`~backend.plugins.host.PluginHost` -- directly, rather than
reimplementing its comparison logic: a plugin declaring an incompatible
``hostApi`` range must be installed as :attr:`PluginState.REJECTED`, and a
compatible one as :attr:`PluginState.INSTALLED`. It also checks the small
standalone helper in ``backend/sdk/host_api.py`` agrees with that real path,
and that every existing per-contract ``*_CONTRACT_HOST_API`` range is
satisfied by :data:`HOST_API_VERSION`.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.evals.contract import EVAL_CONTRACT_HOST_API
from backend.persistence.database import DurableStore
from backend.plugins.host import HOST_API_VERSION, PluginHost, PluginState
from backend.reasoning.contract import REASONING_CONTRACT_HOST_API
from backend.routing.contract import ROUTING_CONTRACT_HOST_API
from backend.sdk.host_api import check_host_api_compatibility


def _write_plugin(root: Path, name: str, *, host_api: str) -> Path:
    """Write a minimal, installable plugin project declaring ``host_api``.

    Args:
        root: Directory to create the plugin project under.
        name: Plugin name, used to derive its id, module, and directory.
        host_api: The ``hostApi`` SemVer range to declare in ``plugin.yaml``.

    Returns:
        The path to the created plugin directory.
    """
    plugin_dir = root / name
    plugin_dir.mkdir()
    module_name = name.replace("-", "_")
    (plugin_dir / f"{module_name}.py").write_text(
        "def register(host):\n"
        "    host.register_extension('skill', 'acme/%s.skill', {})\n" % name,
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
              entrypoint: "{module_name}:register"
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
    """A fresh :class:`PluginHost` backed by a temp sqlite store and plugin directory."""
    store = DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}")
    return PluginHost(store=store, plugin_dirs=[tmp_path / "plugins"])


def test_incompatible_host_api_range_is_rejected(host: PluginHost, tmp_path: Path) -> None:
    """A plugin declaring a hostApi range that excludes the host version is rejected."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = _write_plugin(plugin_root, "future-plugin", host_api=">=3.0 <4.0")

    record = host.install(plugin_dir)

    assert record.state is PluginState.REJECTED
    assert "incompatible" in record.reason


def test_compatible_host_api_range_is_installed(host: PluginHost, tmp_path: Path) -> None:
    """A plugin declaring a hostApi range that includes the host version installs cleanly."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = _write_plugin(plugin_root, "current-plugin", host_api=">=2.0 <3.0")

    record = host.install(plugin_dir)

    assert record.state is PluginState.INSTALLED
    assert record.reason == ""


def test_sdk_helper_agrees_with_the_plugin_host_compatibility_gate() -> None:
    """The standalone SDK helper agrees with PluginHost's install-time decisions."""
    assert check_host_api_compatibility(">=2.0 <3.0", HOST_API_VERSION) is True
    assert check_host_api_compatibility(">=3.0 <4.0", HOST_API_VERSION) is False


@pytest.mark.parametrize(
    "contract_host_api",
    [EVAL_CONTRACT_HOST_API, REASONING_CONTRACT_HOST_API, ROUTING_CONTRACT_HOST_API],
)
def test_existing_contract_host_api_ranges_are_satisfied_by_the_host_version(
    contract_host_api: str,
) -> None:
    """Every published *_CONTRACT_HOST_API range is compatible with HOST_API_VERSION."""
    assert check_host_api_compatibility(contract_host_api, HOST_API_VERSION) is True
