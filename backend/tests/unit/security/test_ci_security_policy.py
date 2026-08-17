"""Assert the CI workflow enforces the E11-S4 HIGH/CRITICAL vuln+license gate.

Parses ``.github/workflows/ci-backend.yml`` directly rather than re-running
CI, so a regression in the workflow file (e.g. someone loosening the
severity threshold) is caught by the fast unit test suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github" / "workflows" / "ci-backend.yml"


def _load_workflow() -> dict[str, Any]:
    """Parse the backend CI workflow YAML.

    Returns:
        The parsed workflow document.
    """
    # `on:` parses as the boolean key True under PyYAML's default YAML 1.1
    # resolver; ci-backend.yml is never round-tripped, only read, so this is
    # safe and avoids depending on a custom loader just for one key name.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _security_baseline_steps() -> list[dict[str, Any]]:
    """Return the ordered steps of the ``security-baseline`` job.

    Returns:
        The job's step list.
    """
    workflow = _load_workflow()
    return workflow["jobs"]["security-baseline"]["steps"]


def _step_named(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """Find one step by its ``name`` field.

    Args:
        steps: Steps to search.
        name: Exact step name.

    Returns:
        The matching step.
    """
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in security-baseline")


def test_trivy_scan_covers_vulnerabilities_and_licenses() -> None:
    """The Trivy step scans both vulnerability and license findings."""
    step = _step_named(
        _security_baseline_steps(), "Run HIGH/CRITICAL vulnerability and license scan"
    )
    scanners = {item.strip() for item in step["with"]["scanners"].split(",")}
    assert scanners == {"vuln", "license"}


def test_trivy_scan_severity_is_high_and_critical_only() -> None:
    """The gate covers HIGH and CRITICAL findings, not every severity."""
    step = _step_named(
        _security_baseline_steps(), "Run HIGH/CRITICAL vulnerability and license scan"
    )
    assert step["with"]["severity"] == "HIGH,CRITICAL"


def test_trivy_scan_fails_the_job_on_findings() -> None:
    """A finding fails the CI job rather than only annotating it."""
    step = _step_named(
        _security_baseline_steps(), "Run HIGH/CRITICAL vulnerability and license scan"
    )
    assert step["with"]["exit-code"] == "1"


def test_trivy_scan_does_not_ignore_unfixed_findings() -> None:
    """Findings without a published fix still gate CI, matching the story's intent."""
    step = _step_named(
        _security_baseline_steps(), "Run HIGH/CRITICAL vulnerability and license scan"
    )
    assert step["with"]["ignore-unfixed"] is False


def test_trivy_scan_uses_the_committed_ignore_file() -> None:
    """The scan is configured against the repository's approved-exceptions file."""
    step = _step_named(
        _security_baseline_steps(), "Run HIGH/CRITICAL vulnerability and license scan"
    )
    assert step["with"]["trivyignores"] == ".trivyignore.yaml"


def test_exception_validation_runs_before_trivy() -> None:
    """Malformed or expired exceptions are caught before the Trivy gate runs."""
    steps = _security_baseline_steps()
    names = [step.get("name") for step in steps]
    validate_index = names.index("Validate expiring security exceptions")
    trivy_index = names.index("Run HIGH/CRITICAL vulnerability and license scan")

    assert validate_index < trivy_index
