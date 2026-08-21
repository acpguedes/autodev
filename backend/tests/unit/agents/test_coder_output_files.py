"""Contract tests for E41-S2: CoderOutput.files (real code-generation contract)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.agents.contracts import (
    CODER_MAX_FILE_BYTES,
    CODER_MAX_FILES,
    CoderFile,
    CoderOutput,
)


def test_coder_output_round_trips_files_additively_with_coding_tasks() -> None:
    payload = {
        "coding_tasks": [{"component": "backend/payments", "task": "Add charge endpoint"}],
        "files": [{"path": "backend/payments/charge.py", "content": "def charge(): ...\n"}],
        "test_updates": ["Add a charge endpoint test"],
        "touched_components": ["backend/payments"],
    }

    output = CoderOutput.model_validate(payload)

    assert output.coding_tasks[0].component == "backend/payments"
    assert output.files == [
        CoderFile(path="backend/payments/charge.py", content="def charge(): ...\n")
    ]


def test_coder_output_files_default_to_empty_list() -> None:
    output = CoderOutput.model_validate({"coding_tasks": []})

    assert output.files == []


def test_coder_output_rejects_too_many_files() -> None:
    files = [{"path": f"f{i}.py", "content": "x"} for i in range(CODER_MAX_FILES + 1)]

    with pytest.raises(ValidationError):
        CoderOutput.model_validate({"files": files})


def test_coder_output_rejects_oversized_file_content() -> None:
    files = [{"path": "big.py", "content": "x" * (CODER_MAX_FILE_BYTES + 1)}]

    with pytest.raises(ValidationError):
        CoderOutput.model_validate({"files": files})


def test_coder_output_accepts_file_at_exact_caps() -> None:
    files = [{"path": f"f{i}.py", "content": "x"} for i in range(CODER_MAX_FILES)]
    files[0]["content"] = "x" * CODER_MAX_FILE_BYTES

    output = CoderOutput.model_validate({"files": files})

    assert len(output.files) == CODER_MAX_FILES
