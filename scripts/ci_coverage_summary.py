#!/usr/bin/env python3
"""Render a Markdown coverage summary from a coverage.py XML report.

Reads ``coverage.xml`` (Cobertura format, produced by
``pytest --cov-report=xml``) and writes a short Markdown table with the
line/branch coverage percentages and a PASS/FAIL verdict against the
configured gate. Used by ``.github/workflows/ci-backend.yml`` to populate
the GitHub Actions job summary on every PR.
"""

from __future__ import annotations

import argparse
import pathlib
import xml.etree.ElementTree as ET


def render_summary(coverage_xml: pathlib.Path, gate: float) -> str:
    """Build the Markdown coverage summary.

    Args:
        coverage_xml: Path to the Cobertura-format coverage XML report.
        gate: The minimum required line-coverage percentage.

    Returns:
        A Markdown string with a coverage summary table, or a fallback
        message if the report file does not exist.
    """
    if not coverage_xml.exists():
        return "Coverage report not generated.\n"

    root = ET.parse(coverage_xml).getroot()
    line_rate = float(root.attrib.get("line-rate", 0)) * 100
    branch_rate = float(root.attrib.get("branch-rate", 0)) * 100
    status = "PASS" if line_rate >= gate else "FAIL"

    return (
        "## Backend coverage (product code, `backend/tests/*` omitted)\n\n"
        "| Metric | Value |\n"
        "| --- | --- |\n"
        f"| Line coverage | {line_rate:.2f}% |\n"
        f"| Branch coverage | {branch_rate:.2f}% |\n"
        f"| Gate | {gate:.0f}% |\n"
        f"| Status | {status} |\n"
    )


def main() -> int:
    """Entry point: parse CLI args, render the summary, and write it out.

    Returns:
        Process exit code (always ``0``; this script never fails the build
        — the coverage gate itself is enforced by pytest-cov).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-xml", type=pathlib.Path, default=pathlib.Path("coverage.xml"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("coverage_summary.md"))
    parser.add_argument("--gate", type=float, default=85.0)
    args = parser.parse_args()

    summary = render_summary(args.coverage_xml, args.gate)
    args.out.write_text(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
