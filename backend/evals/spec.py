"""Parsing and validation for ``eval.yaml`` documents (E5-S3).

Mirrors :func:`backend.reasoning.contract.validate_reasoning_strategy_manifest`:
a raw parsed YAML/JSON document goes in, an :class:`~backend.evals.contract.EvalSpecValidationResult`
comes out, carrying either the parsed, typed :class:`~backend.evals.contract.EvalSpec`
or the list of validation errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from packaging.version import InvalidVersion, Version

from backend.evals.contract import (
    EVAL_ID_RE,
    MODES,
    SEMVER_RE,
    ABTestSpec,
    CostMetricSpec,
    EvalDataset,
    EvalSpec,
    EvalSpecValidationResult,
    EvalTarget,
    EvaluatorSpec,
    GateSpec,
    LatencyMetricSpec,
    MetricsSpec,
    OnlineConfig,
    QualityMetricSpec,
    RubricCriterion,
)


def validate_eval_spec(raw: dict[str, Any]) -> EvalSpecValidationResult:
    """Validate a raw ``eval.yaml`` document and parse it into a spec object.

    Args:
        raw: Parsed ``eval.yaml`` document.

    Returns:
        A result indicating whether the document is valid; on success it
        carries the parsed :class:`~backend.evals.contract.EvalSpec`, on
        failure the list of errors.
    """
    errors: list[str] = []
    for key in ("schemaVersion", "id", "version", "target", "mode", "dataset", "evaluators", "metrics"):
        if key not in raw:
            errors.append(f"{key} is required")

    schema_version = _string(raw.get("schemaVersion"))
    eval_id = _string(raw.get("id"))
    version = _string(raw.get("version"))
    mode = _string(raw.get("mode"))

    if eval_id and not EVAL_ID_RE.match(eval_id):
        errors.append("id must use namespace/name kebab-case format")
    if version and not _is_semver(version):
        errors.append("version must be SemVer MAJOR.MINOR.PATCH")
    if mode and mode not in MODES:
        errors.append(f"mode must be one of {sorted(MODES)}")

    target = _parse_target(raw.get("target"), errors)
    dataset = _parse_dataset(raw.get("dataset"), errors)
    evaluators = _parse_evaluators(raw.get("evaluators"), errors)
    metrics = _parse_metrics(raw.get("metrics"), errors)
    gate = _parse_gate(raw.get("gate"), errors) if raw.get("gate") is not None else None
    online = _parse_online(raw.get("online"), errors) if raw.get("online") is not None else None

    if errors:
        return EvalSpecValidationResult(False, errors)

    return EvalSpecValidationResult(
        True,
        [],
        EvalSpec(
            schema_version=schema_version,
            id=eval_id,
            version=version,
            target=target,
            mode=mode,
            dataset=dataset,
            evaluators=evaluators,
            metrics=metrics,
            gate=gate,
            online=online,
            raw=dict(raw),
        ),
    )


def load_eval_spec(path: Path | str) -> EvalSpec:
    """Load, parse, and validate an ``eval.yaml`` spec from disk.

    Args:
        path: Path to the ``eval.yaml`` file.

    Returns:
        The parsed and validated :class:`~backend.evals.contract.EvalSpec`.

    Raises:
        ValueError: If the document is not a mapping or fails validation.
    """
    spec_path = Path(path)
    raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("eval.yaml must contain a mapping at the document root")
    result = validate_eval_spec(raw)
    if not result.valid or result.spec is None:
        raise ValueError("; ".join(result.errors))
    return result.spec


def _parse_target(raw: Any, errors: list[str]) -> EvalTarget:
    """Parse and validate the ``target`` section of a raw eval spec.

    Args:
        raw: Raw value of the ``target`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed target; empty fields if ``raw`` is not an object.
    """
    if not isinstance(raw, dict):
        errors.append("target must be an object")
        return EvalTarget(kind="", agent_id="")
    kind = _string(raw.get("kind"))
    agent_id = _string(raw.get("agent_id"))
    if not kind:
        errors.append("target.kind is required")
    if not agent_id:
        errors.append("target.agent_id is required")
    reasoning_strategy = _string(raw.get("reasoning_strategy")) or None
    return EvalTarget(kind=kind, agent_id=agent_id, reasoning_strategy=reasoning_strategy)


def _parse_dataset(raw: Any, errors: list[str]) -> EvalDataset:
    """Parse and validate the ``dataset`` section of a raw eval spec.

    Args:
        raw: Raw value of the ``dataset`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed dataset reference; empty ``ref`` if ``raw`` is not an object.
    """
    if not isinstance(raw, dict):
        errors.append("dataset must be an object")
        return EvalDataset(ref="")
    ref = _string(raw.get("ref"))
    if not ref:
        errors.append("dataset.ref is required")
    split = _string(raw.get("split")) or "test"
    try:
        size = int(raw.get("size", 0) or 0)
    except (TypeError, ValueError):
        errors.append("dataset.size must be an integer")
        size = 0
    return EvalDataset(ref=ref, split=split, size=size)


def _parse_evaluators(raw: Any, errors: list[str]) -> tuple[EvaluatorSpec, ...]:
    """Parse and validate the ``evaluators`` list of a raw eval spec.

    Args:
        raw: Raw value of the ``evaluators`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed evaluator specs, in declaration order.
    """
    if not isinstance(raw, list) or not raw:
        errors.append("evaluators must be a non-empty array")
        return ()
    parsed: list[EvaluatorSpec] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(f"evaluators[{index}] must be an object")
            continue
        kind = _string(entry.get("kind"))
        evaluator_id = _string(entry.get("id"))
        if not kind:
            errors.append(f"evaluators[{index}].kind is required")
        if not evaluator_id:
            errors.append(f"evaluators[{index}].id is required")
        check = _string(entry.get("check")) or None
        if kind == "deterministic" and not check:
            errors.append(f"evaluators[{index}] (deterministic) requires 'check'")
        model = _string(entry.get("model")) or None
        rubric = _parse_rubric(entry.get("rubric"), index, errors)
        if kind == "llm-as-judge" and not rubric:
            errors.append(f"evaluators[{index}] (llm-as-judge) requires a non-empty 'rubric'")
        parsed.append(EvaluatorSpec(kind=kind, id=evaluator_id, check=check, model=model, rubric=rubric))

    seen_ids: set[str] = set()
    for evaluator in parsed:
        if evaluator.id and evaluator.id in seen_ids:
            # A duplicate id would silently collapse in the metrics.quality
            # dict (keyed by evaluator id) and in gate-expression lookups —
            # reject it here rather than lose a case's score silently.
            errors.append(f"evaluators contains a duplicate id: {evaluator.id!r}")
        seen_ids.add(evaluator.id)
    return tuple(parsed)


def _parse_rubric(raw: Any, index: int, errors: list[str]) -> dict[str, RubricCriterion]:
    """Parse and validate one evaluator's ``rubric`` mapping.

    Args:
        raw: Raw value of the ``rubric`` field.
        index: Position of the owning evaluator, for error messages.
        errors: Error list to append validation failures to.

    Returns:
        Parsed rubric criteria, keyed by criterion name.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        errors.append(f"evaluators[{index}].rubric must be an object")
        return {}
    criteria: dict[str, RubricCriterion] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict) or "weight" not in entry:
            errors.append(f"evaluators[{index}].rubric.{name} requires 'weight'")
            continue
        try:
            weight = float(entry["weight"])
        except (TypeError, ValueError):
            errors.append(f"evaluators[{index}].rubric.{name}.weight must be numeric")
            continue
        scale_raw = entry.get("scale", [0, 1])
        if not isinstance(scale_raw, (list, tuple)) or len(scale_raw) != 2:
            errors.append(f"evaluators[{index}].rubric.{name}.scale must be a 2-element array")
            continue
        try:
            scale = (float(scale_raw[0]), float(scale_raw[1]))
        except (TypeError, ValueError):
            errors.append(f"evaluators[{index}].rubric.{name}.scale must be numeric")
            continue
        criteria[str(name)] = RubricCriterion(weight=weight, scale=scale)
    return criteria


def _parse_metrics(raw: Any, errors: list[str]) -> MetricsSpec:
    """Parse and validate the ``metrics`` section of a raw eval spec.

    Args:
        raw: Raw value of the ``metrics`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed metrics configuration; each dimension is optional.
    """
    if not isinstance(raw, dict):
        errors.append("metrics must be an object")
        return MetricsSpec()
    quality: QualityMetricSpec | None = None
    if raw.get("quality") is not None:
        quality_raw = raw["quality"]
        if not isinstance(quality_raw, dict) or not _string(quality_raw.get("primary")):
            errors.append("metrics.quality requires 'primary'")
        else:
            quality = QualityMetricSpec(
                primary=_string(quality_raw.get("primary")),
                aggregate=_string(quality_raw.get("aggregate")) or "mean",
                min_pass_rate=_optional_float(quality_raw.get("min_pass_rate")),
            )
    cost: CostMetricSpec | None = None
    if raw.get("cost") is not None:
        cost_raw = raw["cost"] or {}
        cost = CostMetricSpec(budget_usd_p95=_optional_float(cost_raw.get("budget_usd_p95")))
    latency: LatencyMetricSpec | None = None
    if raw.get("latency") is not None:
        latency_raw = raw["latency"] or {}
        latency = LatencyMetricSpec(p95_seconds=_optional_float(latency_raw.get("p95_seconds")))
    return MetricsSpec(quality=quality, cost=cost, latency=latency)


def _parse_gate(raw: Any, errors: list[str]) -> GateSpec | None:
    """Parse and validate the optional ``gate`` section of a raw eval spec.

    Args:
        raw: Raw value of the ``gate`` field.
        errors: Error list to append validation failures to.

    Returns:
        The parsed gate, or ``None`` if invalid (an error is recorded).
    """
    if not isinstance(raw, dict) or not _string(raw.get("fail_if")):
        errors.append("gate.fail_if is required when gate is present")
        return None
    return GateSpec(fail_if=_string(raw.get("fail_if")))


def _parse_online(raw: Any, errors: list[str]) -> OnlineConfig | None:
    """Parse and validate the optional ``online`` section of a raw eval spec.

    Args:
        raw: Raw value of the ``online`` field.
        errors: Error list to append validation failures to.

    Returns:
        The parsed online config, or ``None`` if invalid (an error is recorded).
    """
    if not isinstance(raw, dict):
        errors.append("online must be an object")
        return None
    publish_scores = bool(raw.get("publish_scores", False))
    ab_test: ABTestSpec | None = None
    ab_test_raw = raw.get("ab_test")
    if ab_test_raw is not None:
        if not isinstance(ab_test_raw, dict):
            errors.append("online.ab_test must be an object")
        else:
            ab_test = ABTestSpec(
                control=dict(ab_test_raw.get("control") or {}),
                variant=dict(ab_test_raw.get("variant") or {}),
                traffic=dict(ab_test_raw.get("traffic") or {}),
                promote_if=_string(ab_test_raw.get("promote_if")),
                min_samples=int(ab_test_raw.get("min_samples", 0) or 0),
            )
    return OnlineConfig(publish_scores=publish_scores, ab_test=ab_test)


def _optional_float(value: Any) -> float | None:
    """Coerce a value to ``float``, returning ``None`` if it cannot be parsed.

    Args:
        value: Value to coerce.

    Returns:
        The coerced float, or ``None`` if ``value`` is ``None`` or invalid.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string(value: Any) -> str:
    """Coerce a value to a string, defaulting to empty when not a string.

    Args:
        value: Value to coerce.

    Returns:
        ``value`` if it is already a ``str``, otherwise an empty string.
    """
    return value if isinstance(value, str) else ""


def _is_semver(value: str) -> bool:
    """Check whether a string is a valid ``MAJOR.MINOR.PATCH`` SemVer version.

    Args:
        value: Candidate version string.

    Returns:
        ``True`` if ``value`` is a valid SemVer version, ``False`` otherwise.
    """
    if not SEMVER_RE.match(value):
        return False
    try:
        Version(value)
    except InvalidVersion:
        return False
    return True


__all__ = ["load_eval_spec", "validate_eval_spec"]
