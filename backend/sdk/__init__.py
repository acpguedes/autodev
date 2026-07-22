"""AutoDev plugin SDK."""

from backend.sdk.contracts import (
    SDK_CONTRACT_VERSION,
    ContractTestResult,
    ExtensionRegistration,
    HostApi,
    PluginManifest,
    PluginRegister,
)
from backend.sdk.host_api import check_host_api_compatibility
from backend.sdk.scaffold import scaffold_plugin
from backend.sdk.testing import run_contract_tests

__all__ = [
    "ContractTestResult",
    "ExtensionRegistration",
    "HostApi",
    "PluginManifest",
    "PluginRegister",
    "SDK_CONTRACT_VERSION",
    "check_host_api_compatibility",
    "run_contract_tests",
    "scaffold_plugin",
]
