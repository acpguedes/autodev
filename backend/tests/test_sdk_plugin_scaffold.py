from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from backend.sdk.cli import main as sdk_main
from backend.sdk.testing import run_contract_tests


def test_sdk_new_plugin_scaffolds_project_that_passes_contract_tests(tmp_path: Path) -> None:
    output = tmp_path / "hello-plugin"

    exit_code = sdk_main(["new", "plugin", "acme/hello-plugin", "--output", str(output)])

    assert exit_code == 0
    assert (output / "plugin.yaml").exists()
    assert (output / "hello_plugin.py").exists()
    assert (output / "tests" / "test_contract.py").exists()
    assert run_contract_tests(output).passed is True


def test_scaffolded_contract_test_is_runnable_with_pytest(tmp_path: Path) -> None:
    output = tmp_path / "hello-plugin"
    sdk_main(["new", "plugin", "acme/hello-plugin", "--output", str(output)])

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(output / "tests" / "test_contract.py"), "-q"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_contract_harness_reports_manifest_failures(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "bad-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text("id: nope\n", encoding="utf-8")

    result = run_contract_tests(plugin_dir)

    assert result.passed is False
    assert "schemaVersion is required" in result.errors


def test_typescript_contract_stub_is_published() -> None:
    contract_stub = Path("sdk/typescript/contracts.ts")

    assert contract_stub.exists()
    assert "export interface PluginManifest" in contract_stub.read_text(encoding="utf-8")
