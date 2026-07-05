"""Project scaffolding for Python plugins."""

from __future__ import annotations

import re
from pathlib import Path

from backend.plugins.manifest import PLUGIN_ID_RE


def scaffold_plugin(plugin_id: str, output: Path | str) -> Path:
    """Scaffold a minimal Python plugin project with a manifest, entrypoint, and tests.

    Args:
        plugin_id: Plugin id in ``namespace/name`` kebab-case format.
        output: Directory to create the project in; must not already exist.

    Returns:
        The created project directory.

    Raises:
        ValueError: If ``plugin_id`` is not in the required format.
        FileExistsError: If ``output`` already exists.
    """
    if not PLUGIN_ID_RE.match(plugin_id):
        raise ValueError("plugin id must use namespace/name kebab-case format")
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=False)
    name = plugin_id.split("/", 1)[1]
    module_name = _module_name(name)

    _write(
        output_path / "plugin.yaml",
        f"""
schemaVersion: "1"
id: "{plugin_id}"
name: "{name.replace('-', ' ').title()}"
version: "0.1.0"
hostApi: ">=2.0 <3.0"
runtime:
  loader: "in-process"
  entrypoint: "{module_name}:register"
permissions: {{}}
extensionPoints:
  - kind: "skill"
    id: "{plugin_id}.skill"
    contract: "^1.0"
""".strip()
        + "\n",
    )
    _write(
        output_path / f"{module_name}.py",
        f"""
from __future__ import annotations

from backend.sdk.contracts import HostApi


def register(host: HostApi) -> None:
    host.register_extension("skill", "{plugin_id}.skill", {{"label": "Hello plugin"}})
""".lstrip(),
    )
    tests_dir = output_path / "tests"
    tests_dir.mkdir()
    _write(
        tests_dir / "test_contract.py",
        """
from pathlib import Path

from backend.sdk.testing import run_contract_tests


def test_plugin_contracts_pass() -> None:
    result = run_contract_tests(Path(__file__).parents[1])
    assert result.passed, result.errors
""".lstrip(),
    )
    _write(
        output_path / "pyproject.toml",
        f"""
[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["autodev-architect"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""".strip()
        + "\n",
    )
    _write(
        output_path / "README.md",
        f"""
# {name}

Run contract tests from an AutoDev checkout:

```bash
python -m pytest tests -q
```
""".lstrip(),
    )
    return output_path


def _module_name(name: str) -> str:
    """Derive a valid Python module name from a plugin's kebab-case name segment."""
    return re.sub(r"[^a-z0-9_]", "_", name.replace("-", "_"))


def _write(path: Path, content: str) -> None:
    """Write UTF-8 text content to a file."""
    path.write_text(content, encoding="utf-8")


__all__ = ["scaffold_plugin"]
