"""Reference dataset loader for on-demand/CI eval triggers (E12-S3).

Resolving an eval spec's ``dataset.ref`` into concrete
:class:`~backend.evals.contract.EvalCase` objects is explicitly out of scope
for the Evaluation Service itself (see ``docs/evals/spec.md``'s
"Dataset-loading scope boundary" — there is no Context/RAG Service (E7) yet to
back a golden-set store). This module is the opt-in loader used by the
``autodev eval run`` CLI command (:mod:`backend.cli_plugins.evals`) and the
``make eval-reference`` target: it treats ``dataset.ref`` as a path to a local
YAML/JSON file, relative to the eval spec's own directory, containing a
``cases:`` list of ``{case_id, payload}`` entries.

This module is purely additive — it does not modify
:mod:`backend.evals.service`, :mod:`backend.evals.runner`, or
:mod:`backend.evals.contract` in any way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.evals.contract import EvalCase


class EvalDatasetError(RuntimeError):
    """Raised when a reference dataset file is missing, malformed, or empty."""


def resolve_dataset_path(spec_path: Path | str, dataset_ref: str) -> Path:
    """Resolve an eval spec's ``dataset.ref`` to a filesystem path.

    ``dataset_ref`` is interpreted as a path relative to the directory
    containing the eval spec file, matching the reference eval's convention
    (see ``evals/reference/agent_smoke/eval.yaml``).

    Args:
        spec_path: Path to the ``eval.yaml`` spec file that declared
            ``dataset_ref``.
        dataset_ref: The spec's ``dataset.ref`` value.

    Returns:
        The resolved, absolute dataset file path. Not guaranteed to exist —
        callers should handle the resulting error from
        :func:`load_eval_cases`.
    """
    ref_path = Path(dataset_ref)
    if ref_path.is_absolute():
        return ref_path
    return Path(spec_path).resolve().parent / ref_path


def load_eval_cases(path: Path | str) -> list[EvalCase]:
    """Load a local dataset file (YAML or JSON) into a list of ``EvalCase``.

    Args:
        path: Path to the dataset file. Must parse to a mapping with a
            ``cases`` key holding a non-empty list of ``{case_id, payload}``
            entries; ``payload`` defaults to ``{}`` when omitted.

    Returns:
        The parsed :class:`~backend.evals.contract.EvalCase` objects, in file
        order.

    Raises:
        EvalDatasetError: If the file does not exist, is not a mapping with a
            ``cases`` list, or a case entry is malformed (missing/empty
            ``case_id``, or a non-object ``payload``).
    """
    dataset_path = Path(path)
    if not dataset_path.is_file():
        raise EvalDatasetError(f"dataset file not found: {dataset_path}")

    try:
        raw: Any = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EvalDatasetError(f"{dataset_path}: invalid YAML/JSON: {exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise EvalDatasetError(f"{dataset_path} must be a mapping with a 'cases' list")

    cases: list[EvalCase] = []
    for index, entry in enumerate(raw["cases"]):
        if not isinstance(entry, dict) or not entry.get("case_id"):
            raise EvalDatasetError(f"{dataset_path}: cases[{index}] requires a non-empty 'case_id'")
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            raise EvalDatasetError(f"{dataset_path}: cases[{index}].payload must be an object")
        cases.append(EvalCase(case_id=str(entry["case_id"]), payload=dict(payload)))

    if not cases:
        raise EvalDatasetError(f"{dataset_path} contains no cases")

    return cases


__all__ = ["EvalDatasetError", "load_eval_cases", "resolve_dataset_path"]
