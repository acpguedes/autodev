"""Unit tests for the reference dataset loader (backend/evals/dataset_loader.py).

Covers ``resolve_dataset_path`` (relative and absolute ``dataset.ref`` values)
and ``load_eval_cases`` (valid load plus every malformed-input error path).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.evals.contract import EvalCase
from backend.evals.dataset_loader import EvalDatasetError, load_eval_cases, resolve_dataset_path


def test_resolve_dataset_path_relative_to_spec_directory(tmp_path: Path) -> None:
    """A relative ``dataset.ref`` resolves against the spec file's own directory."""
    spec_dir = tmp_path / "evals" / "reference" / "agent_smoke"
    spec_dir.mkdir(parents=True)
    spec_path = spec_dir / "eval.yaml"
    spec_path.write_text("schemaVersion: '1.0'\n")

    resolved = resolve_dataset_path(spec_path, "dataset.yaml")

    assert resolved == (spec_dir / "dataset.yaml").resolve()


def test_resolve_dataset_path_absolute_ref_is_returned_as_is(tmp_path: Path) -> None:
    """An absolute ``dataset.ref`` is returned unchanged, ignoring the spec's directory."""
    spec_path = tmp_path / "sub" / "eval.yaml"
    absolute_ref = tmp_path / "elsewhere" / "dataset.yaml"

    resolved = resolve_dataset_path(spec_path, str(absolute_ref))

    assert resolved == absolute_ref


def test_load_eval_cases_parses_valid_dataset(tmp_path: Path) -> None:
    """A well-formed dataset file parses into the expected ``EvalCase`` list."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text(
        "cases:\n"
        "  - case_id: case-one\n"
        "    payload:\n"
        "      key: value\n"
        "  - case_id: case-two\n"
    )

    cases = load_eval_cases(dataset_path)

    assert cases == [
        EvalCase(case_id="case-one", payload={"key": "value"}),
        EvalCase(case_id="case-two", payload={}),
    ]


def test_load_eval_cases_accepts_path_as_str(tmp_path: Path) -> None:
    """``load_eval_cases`` accepts a plain string path, not just a ``Path``."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("cases:\n  - case_id: only-case\n")

    cases = load_eval_cases(str(dataset_path))

    assert cases == [EvalCase(case_id="only-case", payload={})]


def test_load_eval_cases_missing_file_raises(tmp_path: Path) -> None:
    """A missing dataset file raises ``EvalDatasetError``."""
    missing = tmp_path / "does-not-exist.yaml"

    with pytest.raises(EvalDatasetError, match="dataset file not found"):
        load_eval_cases(missing)


def test_load_eval_cases_invalid_yaml_raises(tmp_path: Path) -> None:
    """Unparseable YAML content raises ``EvalDatasetError``."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("cases: [unterminated\n")

    with pytest.raises(EvalDatasetError, match="invalid YAML/JSON"):
        load_eval_cases(dataset_path)


def test_load_eval_cases_non_mapping_root_raises(tmp_path: Path) -> None:
    """A dataset file that does not parse to a mapping raises ``EvalDatasetError``."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("- just\n- a\n- list\n")

    with pytest.raises(EvalDatasetError, match="must be a mapping with a 'cases' list"):
        load_eval_cases(dataset_path)


def test_load_eval_cases_missing_cases_key_raises(tmp_path: Path) -> None:
    """A mapping without a ``cases`` list raises ``EvalDatasetError``."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("split: test\n")

    with pytest.raises(EvalDatasetError, match="must be a mapping with a 'cases' list"):
        load_eval_cases(dataset_path)


def test_load_eval_cases_case_missing_case_id_raises(tmp_path: Path) -> None:
    """A case entry without a ``case_id`` raises ``EvalDatasetError``."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("cases:\n  - payload:\n      key: value\n")

    with pytest.raises(EvalDatasetError, match=r"cases\[0\] requires a non-empty 'case_id'"):
        load_eval_cases(dataset_path)


def test_load_eval_cases_case_empty_case_id_raises(tmp_path: Path) -> None:
    """A case entry with an empty ``case_id`` raises ``EvalDatasetError``."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("cases:\n  - case_id: ''\n")

    with pytest.raises(EvalDatasetError, match=r"cases\[0\] requires a non-empty 'case_id'"):
        load_eval_cases(dataset_path)


def test_load_eval_cases_case_not_a_mapping_raises(tmp_path: Path) -> None:
    """A non-mapping case entry raises ``EvalDatasetError``."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("cases:\n  - just-a-string\n")

    with pytest.raises(EvalDatasetError, match=r"cases\[0\] requires a non-empty 'case_id'"):
        load_eval_cases(dataset_path)


def test_load_eval_cases_non_object_payload_raises(tmp_path: Path) -> None:
    """A case with a non-object ``payload`` raises ``EvalDatasetError``."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("cases:\n  - case_id: case-one\n    payload: not-an-object\n")

    with pytest.raises(EvalDatasetError, match=r"cases\[0\]\.payload must be an object"):
        load_eval_cases(dataset_path)


def test_load_eval_cases_empty_list_raises(tmp_path: Path) -> None:
    """A dataset with an empty ``cases`` list raises ``EvalDatasetError``."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("cases: []\n")

    with pytest.raises(EvalDatasetError, match="contains no cases"):
        load_eval_cases(dataset_path)


def test_load_eval_cases_second_case_error_reports_correct_index(tmp_path: Path) -> None:
    """Errors report the 0-based index of the offending case, not just the first."""
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text("cases:\n  - case_id: ok-case\n  - case_id: ''\n")

    with pytest.raises(EvalDatasetError, match=r"cases\[1\] requires a non-empty 'case_id'"):
        load_eval_cases(dataset_path)
