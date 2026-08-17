"""Contracts for the E11-S1 instrumentation overhead benchmark."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "measure_observability_overhead.py"


def _load_overhead_module() -> ModuleType:
    """Import the overhead benchmark from its repository script path.

    Returns:
        Imported benchmark module.
    """
    if not SCRIPT.exists():
        pytest.fail(f"missing benchmark script: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("observability_overhead", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_overhead_ratio_is_relative_to_baseline() -> None:
    """The ratio expresses instrumentation cost relative to the baseline."""
    module = _load_overhead_module()
    assert module.calculate_overhead_ratio(10.0, 10.4) == pytest.approx(0.04)


def test_overhead_result_fails_at_the_five_percent_boundary() -> None:
    """A ratio at exactly the 5% boundary is not within target."""
    module = _load_overhead_module()
    result = module.OverheadResult(
        baseline_seconds=10.0,
        instrumented_seconds=10.5,
        overhead_ratio=0.05,
        rounds=7,
        iterations_per_round=200,
    )
    assert result.within_target is False
