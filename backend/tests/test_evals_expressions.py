"""Unit tests for the E5-S3 safe boolean-expression evaluator.

Covers the supported grammar (dotted identifiers, comparisons, boolean
operators, unary +/-, bare true/false/null literals) and its safety
boundary (unknown identifiers/fields and unsupported syntax raise
:class:`ExpressionError` rather than executing arbitrary code).
"""

from __future__ import annotations

import pytest

from backend.evals.expressions import ExpressionError, evaluate_expression


def test_dotted_attribute_comparison() -> None:
    """A dotted-path attribute compares correctly against a literal."""
    assert evaluate_expression("patch.dry_run.ok == true", {"patch": {"dry_run": {"ok": True}}}) is True
    assert evaluate_expression("patch.dry_run.ok == true", {"patch": {"dry_run": {"ok": False}}}) is False


def test_numeric_comparisons() -> None:
    """Numeric comparisons (<, <=, >, >=, ==, !=) evaluate correctly."""
    context = {"sandbox": {"tests": {"exit_code": 0}}}
    assert evaluate_expression("sandbox.tests.exit_code == 0", context) is True
    assert evaluate_expression("sandbox.tests.exit_code != 0", context) is False
    assert evaluate_expression("sandbox.tests.exit_code < 1", context) is True
    assert evaluate_expression("sandbox.tests.exit_code <= 0", context) is True
    assert evaluate_expression("sandbox.tests.exit_code > -1", context) is True


def test_negative_numeric_literal() -> None:
    """A unary-minus numeric literal evaluates correctly (regression: previously unsupported)."""
    assert evaluate_expression("cost.usd_p95 > -0.01", {"cost": {"usd_p95": 0.1}}) is True
    assert evaluate_expression("cost.usd_p95 > -0.01", {"cost": {"usd_p95": -1.0}}) is False


def test_unary_plus_numeric_literal() -> None:
    """A unary-plus numeric literal evaluates correctly."""
    assert evaluate_expression("cost.usd_p95 == +0.5", {"cost": {"usd_p95": 0.5}}) is True


def test_boolean_and_or_not() -> None:
    """and/or/not combine sub-expressions per standard boolean semantics."""
    context = {"quality": {"tests_pass": {"mean": 0.5}}, "cost": {"usd_p95": 0.5}}
    assert evaluate_expression("quality.tests_pass.mean < 0.80 or cost.usd_p95 > 0.35", context) is True
    assert evaluate_expression("quality.tests_pass.mean < 0.80 and cost.usd_p95 > 0.35", context) is True
    assert evaluate_expression("not (quality.tests_pass.mean < 0.80)", context) is False


def test_bare_literals_true_false_null() -> None:
    """The bare identifiers true/false/null resolve to Python True/False/None."""
    assert evaluate_expression("true == true", {}) is True
    assert evaluate_expression("false == false", {}) is True
    assert evaluate_expression("null == null", {}) is True
    assert evaluate_expression("true == false", {}) is False


def test_chained_comparison() -> None:
    """A chained comparison (a < b < c) evaluates left-to-right like Python."""
    assert evaluate_expression("0 < value < 10", {"value": 5}) is True
    assert evaluate_expression("0 < value < 10", {"value": 15}) is False


def test_unknown_identifier_raises() -> None:
    """Referencing a variable not present in the context raises ExpressionError."""
    with pytest.raises(ExpressionError):
        evaluate_expression("unknown_var == 1", {})


def test_unknown_field_raises() -> None:
    """Accessing a field absent from a mapping raises ExpressionError."""
    with pytest.raises(ExpressionError):
        evaluate_expression("sandbox.missing_field == 1", {"sandbox": {}})


def test_access_on_non_mapping_raises() -> None:
    """Dotted access into a non-mapping value raises ExpressionError."""
    with pytest.raises(ExpressionError):
        evaluate_expression("value.attr == 1", {"value": 5})


def test_invalid_syntax_raises() -> None:
    """Syntactically invalid expressions raise ExpressionError, not a bare SyntaxError."""
    with pytest.raises(ExpressionError):
        evaluate_expression("this is not : valid python (((", {})


def test_hyphenated_identifier_is_unsupported() -> None:
    """A hyphenated identifier parses as subtraction, not a single dotted name (documented limitation)."""
    # "quality.tests-pass" parses as "quality.tests - pass", where "pass" is a
    # Python keyword and thus a SyntaxError -> ExpressionError, demonstrating
    # why evaluator/metric ids must use underscores, not hyphens.
    with pytest.raises(ExpressionError):
        evaluate_expression("quality.tests-pass.mean < 0.80", {})
