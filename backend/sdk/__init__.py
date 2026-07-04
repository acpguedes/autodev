"""AutoDev plugin SDK."""

from backend.sdk.contracts import (
    SDK_CONTRACT_VERSION,
    ContractTestResult,
    ExtensionRegistration,
    HostApi,
    PluginManifest,
    PluginRegister,
)
from backend.sdk.scaffold import scaffold_plugin
from backend.sdk.testing import run_contract_tests

__all__ = [
    "ContractTestResult",
    "ExtensionRegistration",
    "HostApi",
    "PluginManifest",
    "PluginRegister",
    "SDK_CONTRACT_VERSION",
    "run_contract_tests",
    "scaffold_plugin",
]
