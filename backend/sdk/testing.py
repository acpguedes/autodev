"""Contract-test harness for plugin authors."""

from __future__ import annotations

import tempfile
from pathlib import Path

from backend.persistence.database import DurableStore
from backend.plugins.host import PluginHost, PluginState
from backend.plugins.manifest import load_manifest
from backend.sdk.contracts import ContractTestResult


def run_contract_tests(plugin_dir: Path | str) -> ContractTestResult:
    """Install and enable a plugin in an ephemeral host to verify it satisfies the SDK contract.

    Args:
        plugin_dir: Directory containing the plugin's ``plugin.yaml``.

    Returns:
        The contract test outcome: passed, or failed with error messages.
    """
    plugin_path = Path(plugin_dir)
    try:
        manifest = load_manifest(plugin_path / "plugin.yaml")
    except Exception as exc:  # noqa: BLE001 - surfaced to plugin authors
        return ContractTestResult(passed=False, errors=tuple(str(exc).split("; ")))

    with tempfile.TemporaryDirectory(prefix="autodev-plugin-contract-") as tmp:
        store = DurableStore(f"sqlite:///{Path(tmp) / 'contract.db'}")
        host = PluginHost(store=store, workspace=plugin_path)
        try:
            installed = host.install(plugin_path)
            if installed.state is not PluginState.INSTALLED:
                return ContractTestResult(False, manifest.id, (installed.reason,))
            enabled = host.enable(manifest.id)
        except Exception as exc:  # noqa: BLE001 - surfaced to plugin authors
            return ContractTestResult(False, manifest.id, (str(exc),))
    if enabled.state is not PluginState.ENABLED:
        return ContractTestResult(False, manifest.id, (enabled.reason,))
    return ContractTestResult(True, manifest.id, ())


__all__ = ["run_contract_tests"]
