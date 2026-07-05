"""Safe boolean-expression evaluator for deterministic checks and quality gates.

Both a deterministic :class:`~backend.evals.contract.EvaluatorSpec` (``check``,
e.g. ``"patch.dry_run.ok == true"``) and a quality gate (``gate.fail_if``, e.g.
``"quality.tests_pass.mean < 0.80 or cost.usd_p95 > 0.35"``) express a small
boolean condition over a dotted-path context. Rather than call :func:`eval`,
this module parses the expression into a Python AST and walks a restricted
node whitelist, resolving dotted identifiers against a supplied mapping.

Supported grammar: dotted identifiers (``a.b.c``), numeric/string literals
(including unary ``-``/``+``, e.g. ``-0.01``), the bare literals
``true``/``false``/``null``, comparisons (``==``, ``!=``, ``<``, ``<=``,
``>``, ``>=``), boolean ``and``/``or``/``not``, and parentheses. Identifiers
must be valid Python identifiers joined by dots — hyphens are not supported
because they parse as subtraction (see ``docs/evals/spec.md``).
"""

from __future__ import annotations

import ast
from typing import Any, Mapping

#: AST comparison node types this evaluator is willing to execute.
_ALLOWED_COMPARE_OPS: dict[type, Any] = {
    ast.Eq: lambda left, right: left == right,
    ast.NotEq: lambda left, right: left != right,
    ast.Lt: lambda left, right: left < right,
    ast.LtE: lambda left, right: left <= right,
    ast.Gt: lambda left, right: left > right,
    ast.GtE: lambda left, right: left >= right,
}

#: Bare identifiers treated as literals rather than context lookups.
_BARE_LITERALS: dict[str, Any] = {"true": True, "false": False, "null": None}


class ExpressionError(ValueError):
    """Raised when an expression is syntactically invalid or uses unsupported syntax."""


def evaluate_expression(expression: str, context: Mapping[str, Any]) -> bool:
    """Safely evaluate a dotted-path boolean expression against a context mapping.

    Args:
        expression: The boolean expression, e.g. ``"patch.dry_run.ok == true"``.
        context: Mapping the expression's dotted identifiers resolve against.

    Returns:
        The boolean result of the expression.

    Raises:
        ExpressionError: If the expression has invalid syntax, references an
            unknown field, or uses a construct outside the supported grammar.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression syntax: {expression!r}") from exc
    return bool(_eval_node(tree.body, context))


def _eval_node(node: ast.AST, context: Mapping[str, Any]) -> Any:
    """Recursively evaluate one AST node against ``context``.

    Args:
        node: AST node to evaluate.
        context: Mapping dotted identifiers resolve against.

    Returns:
        The Python value the node evaluates to.

    Raises:
        ExpressionError: If the node (or an operator/identifier it uses) is
            outside the supported grammar.
    """
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, context)
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(value, context) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ExpressionError("unsupported boolean operator")  # pragma: no cover - defensive
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not _eval_node(node.operand, context)
        if isinstance(node.op, ast.USub):
            return -_eval_node(node.operand, context)
        if isinstance(node.op, ast.UAdd):
            return +_eval_node(node.operand, context)
        raise ExpressionError(f"unsupported unary operator: {type(node.op).__name__}")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        result = True
        for op, comparator in zip(node.ops, node.comparators):
            func = _ALLOWED_COMPARE_OPS.get(type(op))
            if func is None:
                raise ExpressionError(f"unsupported comparison operator: {type(op).__name__}")
            right = _eval_node(comparator, context)
            result = result and bool(func(left, right))
            left = right
        return result
    if isinstance(node, ast.Attribute):
        base = _eval_node(node.value, context)
        if not isinstance(base, Mapping):
            raise ExpressionError(f"cannot access {node.attr!r} on non-mapping value")
        if node.attr not in base:
            raise ExpressionError(f"unknown field {node.attr!r}")
        return base[node.attr]
    if isinstance(node, ast.Name):
        if node.id in _BARE_LITERALS:
            return _BARE_LITERALS[node.id]
        if node.id not in context:
            raise ExpressionError(f"unknown variable {node.id!r}")
        return context[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    raise ExpressionError(f"unsupported expression element: {type(node).__name__}")


__all__ = ["ExpressionError", "evaluate_expression"]
