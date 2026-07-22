"""Unit tests for the ``eval`` CLI plugin (backend/cli_plugins/evals.py).

Covers ``autodev eval run`` end-to-end through ``backend.cli.main``: gate
pass/fail exit codes, spec/dataset load errors, the ``mode != "offline"``
rejection, ``--dataset``/``--run-id`` overrides, persisted-result retrieval
via the store, and the reference eval shipped at
``evals/reference/agent_smoke/eval.yaml``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest

from backend.cli import main
from backend.config.settings import reset_settings_cache
from backend.evals.contract import EvalError
from backend.evals.service import EvaluationService
from backend.persistence.database import get_store, reset_store_cache

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REFERENCE_SPEC = _REPO_ROOT / "evals" / "reference" / "agent_smoke" / "eval.yaml"


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Isolate each test in its own database, config file, and working directory."""
    database_path = tmp_path / "cli.db"
    config_path = tmp_path / "autodev.config.json"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("AUTODEV_PROJECT_ROOT", raising=False)
    reset_store_cache()
    reset_settings_cache()

    yield

    reset_store_cache()
    reset_settings_cache()


def _write_spec_and_dataset(
    tmp_path: Path,
    *,
    fail_if: str = "quality.tests_pass.mean < 1.0",
    eval_id: str = "autodev/smoke-fixture",
) -> Path:
    """Write a minimal offline eval spec + matching dataset to ``tmp_path``.

    Args:
        tmp_path: Directory to write the spec and dataset files into.
        fail_if: The gate's ``fail_if`` expression.
        eval_id: The spec's ``id`` field.

    Returns:
        Path to the written ``eval.yaml`` spec file.
    """
    spec_path = tmp_path / "eval.yaml"
    spec_path.write_text(
        "schemaVersion: '1.0'\n"
        f"id: {eval_id}\n"
        "version: 1.0.0\n"
        "target:\n"
        "  kind: agent\n"
        "  agent_id: autodev/agent-coder\n"
        "mode: offline\n"
        "dataset:\n"
        "  ref: dataset.yaml\n"
        "evaluators:\n"
        "  - kind: deterministic\n"
        "    id: tests_pass\n"
        "    check: \"sandbox.tests.exit_code == 0\"\n"
        "metrics:\n"
        "  quality:\n"
        "    primary: tests_pass\n"
        "gate:\n"
        f"  fail_if: \"{fail_if}\"\n"
    )
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("cases:\n  - case_id: only-case\n    payload:\n      sandbox:\n        tests:\n          exit_code: 0\n")
    return spec_path


def test_eval_run_reference_eval_gate_passes(capsys: pytest.CaptureFixture[str]) -> None:
    """The shipped reference eval runs offline and its gate passes (exit 0)."""
    exit_code = main(["eval", "run", str(_REFERENCE_SPEC)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["evalId"] == "autodev/agent-smoke"
    assert payload["gatePassed"] is True
    assert payload["datasetSize"] == 3


def test_eval_run_persists_result_retrievable_via_store(tmp_path: Path) -> None:
    """A run's ``EvalResult`` is persisted and retrievable via the Evaluation Service."""
    exit_code = main(["eval", "run", str(_REFERENCE_SPEC), "--run-id", "cli-persist-check"])
    assert exit_code == 0

    service = EvaluationService(get_store())
    stored = service.get_result("autodev/agent-smoke", "1.0.0", "cli-persist-check")

    assert stored is not None
    assert stored.gate_passed is True
    assert stored.dataset_size == 3

    listed = service.list_results("autodev/agent-smoke", "1.0.0")
    assert any(result.run_id == "cli-persist-check" for result in listed)


def test_eval_run_gate_failure_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A gate that evaluates true (fails) exits ``1`` while still printing the result."""
    spec_path = _write_spec_and_dataset(tmp_path, fail_if="quality.tests_pass.mean >= 0.0")

    exit_code = main(["eval", "run", str(spec_path)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["gatePassed"] is False


def test_eval_run_missing_spec_file_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A nonexistent spec path exits ``2`` with a JSON error on stderr."""
    missing = tmp_path / "missing.yaml"

    exit_code = main(["eval", "run", str(missing)])

    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert exit_code == 2
    assert "failed to load eval spec" in error["error"]


def test_eval_run_invalid_spec_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A spec that fails ``validate_eval_spec`` exits ``2``."""
    spec_path = tmp_path / "eval.yaml"
    spec_path.write_text("schemaVersion: '1.0'\n")

    exit_code = main(["eval", "run", str(spec_path)])

    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert exit_code == 2
    assert "failed to load eval spec" in error["error"]


def test_eval_run_rejects_online_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A spec with ``mode: online`` is rejected with exit ``2`` (only offline is supported)."""
    spec_path = tmp_path / "eval.yaml"
    spec_path.write_text(
        "schemaVersion: '1.0'\n"
        "id: autodev/online-fixture\n"
        "version: 1.0.0\n"
        "target:\n"
        "  kind: agent\n"
        "  agent_id: autodev/agent-coder\n"
        "mode: online\n"
        "dataset:\n"
        "  ref: dataset.yaml\n"
        "evaluators:\n"
        "  - kind: deterministic\n"
        "    id: tests_pass\n"
        "    check: \"sandbox.tests.exit_code == 0\"\n"
        "metrics:\n"
        "  quality:\n"
        "    primary: tests_pass\n"
    )

    exit_code = main(["eval", "run", str(spec_path)])

    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert exit_code == 2
    assert "offline" in error["error"]


def test_eval_run_missing_dataset_file_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A spec whose resolved dataset file does not exist exits ``2``."""
    spec_path = _write_spec_and_dataset(tmp_path)
    (tmp_path / "dataset.yaml").unlink()

    exit_code = main(["eval", "run", str(spec_path)])

    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert exit_code == 2
    assert "dataset file not found" in error["error"]


def test_eval_run_dataset_override_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--dataset`` overrides the spec's ``dataset.ref`` resolution."""
    spec_path = _write_spec_and_dataset(tmp_path)
    (tmp_path / "dataset.yaml").unlink()
    override_dir = tmp_path / "elsewhere"
    override_dir.mkdir()
    override_dataset = override_dir / "custom.yaml"
    override_dataset.write_text(
        "cases:\n  - case_id: override-case\n    payload:\n      sandbox:\n        tests:\n          exit_code: 0\n"
    )

    exit_code = main(["eval", "run", str(spec_path), "--dataset", str(override_dataset)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["datasetSize"] == 1


def test_eval_run_run_id_conflict_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Reusing a ``run_id`` for the same ``(eval_id, eval_version)`` is a persistence conflict."""
    spec_path = _write_spec_and_dataset(tmp_path, eval_id="autodev/conflict-fixture")
    first = main(["eval", "run", str(spec_path), "--run-id", "dup-run"])
    assert first == 0  # gate passes for this fixture's default fail_if

    capsys.readouterr()
    exit_code = main(["eval", "run", str(spec_path), "--run-id", "dup-run"])

    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert exit_code == 2
    assert "eval run failed" in error["error"]


def test_evaluation_service_run_offline_error_is_surfaced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A generic ``EvalError`` from ``run_offline`` (e.g. a mode assertion) exits ``2``."""

    def _boom(self: EvaluationService, spec: object, cases: object, run_id: object = None) -> None:
        raise EvalError("synthetic failure")

    monkeypatch.setattr(EvaluationService, "run_offline", _boom)
    spec_path = _write_spec_and_dataset(tmp_path, eval_id="autodev/boom-fixture")

    exit_code = main(["eval", "run", str(spec_path)])

    assert exit_code == 2
