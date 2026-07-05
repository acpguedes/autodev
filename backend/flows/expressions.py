"""Safe expression language for flow predicates and input bindings.

Flow manifests reference run state through ``{{ ... }}`` template expressions,
e.g. ``{{ nodes.code.output.patch }}`` or
``{{ nodes['apply-and-validate'].output.testsPassed == true }}``. This module
implements a deliberately small, side-effect-free language: path lookups over a
state mapping, literals, comparisons, and boolean operators. There is no
attribute access, no function calls, and no ``eval`` — expressions cannot touch
anything outside the state document they are evaluated against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Union

_TEMPLATE_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<op>==|!=|<=|>=|<|>|\(|\)|\[|\]|\.)
  | (?P<number>-?\d+(?:\.\d+)?)
  | (?P<string>'[^']*'|"[^"]*")
  | (?P<ident>[A-Za-z_][A-Za-z0-9_-]*)
    """,
    re.VERBOSE,
)

_KEYWORDS = frozenset({"and", "or", "not", "true", "false", "null"})
_COMPARISON_OPS = frozenset({"==", "!=", "<", "<=", ">", ">="})


class ExpressionError(ValueError):
    """Raised when an expression cannot be parsed or evaluated."""


@dataclass(frozen=True)
class _Literal:
    """A constant value in an expression AST."""

    value: Any


@dataclass(frozen=True)
class _Path:
    """A state lookup path such as ``nodes.code.output.patch``."""

    segments: tuple[Union[str, int], ...]


@dataclass(frozen=True)
class _Compare:
    """A binary comparison between two operands."""

    op: str
    left: "_Node"
    right: "_Node"


@dataclass(frozen=True)
class _BoolOp:
    """An ``and``/``or`` combination of two operands."""

    op: str
    left: "_Node"
    right: "_Node"


@dataclass(frozen=True)
class _Not:
    """Logical negation of an operand."""

    operand: "_Node"


_Node = Union[_Literal, _Path, _Compare, _BoolOp, _Not]


@dataclass(frozen=True)
class CompiledExpression:
    """A parsed expression ready for repeated evaluation.

    Attributes:
        source: Original expression text (without template braces).
        root: Root node of the parsed AST.
    """

    source: str
    root: _Node

    def paths(self) -> set[tuple[str, ...]]:
        """Collect every state path referenced by the expression.

        Returns:
            A set of path tuples containing only the leading string segments
            of each referenced path (integer indexes truncate the path).
        """
        found: set[tuple[str, ...]] = set()
        _collect_paths(self.root, found)
        return found


class _Tokenizer:
    """Streams tokens for the recursive-descent expression parser."""

    def __init__(self, source: str) -> None:
        """Tokenize the given expression source.

        Args:
            source: Expression text to tokenize.

        Raises:
            ExpressionError: If the source contains an unrecognized character.
        """
        self.tokens: list[tuple[str, str]] = []
        pos = 0
        while pos < len(source):
            match = _TOKEN_RE.match(source, pos)
            if match is None:
                raise ExpressionError(
                    f"unexpected character {source[pos]!r} in expression {source!r}"
                )
            pos = match.end()
            kind = str(match.lastgroup)
            if kind == "ws":
                continue
            self.tokens.append((kind, match.group()))
        self.index = 0

    def peek(self) -> tuple[str, str] | None:
        """Return the next token without consuming it, or ``None`` at the end."""
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def next(self) -> tuple[str, str]:
        """Consume and return the next token.

        Returns:
            The ``(kind, text)`` token pair.

        Raises:
            ExpressionError: If there are no tokens left.
        """
        token = self.peek()
        if token is None:
            raise ExpressionError("unexpected end of expression")
        self.index += 1
        return token

    def accept(self, text: str) -> bool:
        """Consume the next token when it matches ``text``.

        Args:
            text: Exact token text to match.

        Returns:
            ``True`` when the token matched and was consumed.
        """
        token = self.peek()
        if token is not None and token[1] == text:
            self.index += 1
            return True
        return False

    def expect(self, text: str) -> None:
        """Consume the next token, requiring it to match ``text``.

        Args:
            text: Exact token text required.

        Raises:
            ExpressionError: If the next token does not match.
        """
        token = self.peek()
        if token is None or token[1] != text:
            raise ExpressionError(f"expected {text!r} in expression")
        self.index += 1


def compile_expression(source: str) -> CompiledExpression:
    """Parse an expression into a reusable compiled form.

    Args:
        source: Expression text, without the surrounding ``{{ }}`` braces.

    Returns:
        The compiled expression.

    Raises:
        ExpressionError: If the expression has invalid syntax.
    """
    text = source.strip()
    if not text:
        raise ExpressionError("expression is empty")
    tokenizer = _Tokenizer(text)
    root = _parse_or(tokenizer)
    if tokenizer.peek() is not None:
        raise ExpressionError(f"unexpected trailing tokens in expression {source!r}")
    return CompiledExpression(source=text, root=root)


def _parse_or(tokens: _Tokenizer) -> _Node:
    """Parse an ``or`` chain."""
    node = _parse_and(tokens)
    while _peek_keyword(tokens) == "or":
        tokens.next()
        node = _BoolOp(op="or", left=node, right=_parse_and(tokens))
    return node


def _parse_and(tokens: _Tokenizer) -> _Node:
    """Parse an ``and`` chain."""
    node = _parse_not(tokens)
    while _peek_keyword(tokens) == "and":
        tokens.next()
        node = _BoolOp(op="and", left=node, right=_parse_not(tokens))
    return node


def _parse_not(tokens: _Tokenizer) -> _Node:
    """Parse an optional ``not`` prefix."""
    if _peek_keyword(tokens) == "not":
        tokens.next()
        return _Not(operand=_parse_not(tokens))
    return _parse_comparison(tokens)


def _parse_comparison(tokens: _Tokenizer) -> _Node:
    """Parse an optional binary comparison."""
    left = _parse_operand(tokens)
    token = tokens.peek()
    if token is not None and token[1] in _COMPARISON_OPS:
        op = tokens.next()[1]
        right = _parse_operand(tokens)
        return _Compare(op=op, left=left, right=right)
    return left


def _parse_operand(tokens: _Tokenizer) -> _Node:
    """Parse a literal, path, or parenthesized sub-expression."""
    token = tokens.peek()
    if token is None:
        raise ExpressionError("unexpected end of expression")
    kind, text = token
    if text == "(":
        tokens.next()
        node = _parse_or(tokens)
        tokens.expect(")")
        return node
    if kind == "number":
        tokens.next()
        return _Literal(float(text) if "." in text else int(text))
    if kind == "string":
        tokens.next()
        return _Literal(text[1:-1])
    if kind == "ident":
        if text in {"true", "false"}:
            tokens.next()
            return _Literal(text == "true")
        if text == "null":
            tokens.next()
            return _Literal(None)
        if text in _KEYWORDS:
            raise ExpressionError(f"unexpected keyword {text!r} in expression")
        return _parse_path(tokens)
    raise ExpressionError(f"unexpected token {text!r} in expression")


def _parse_path(tokens: _Tokenizer) -> _Path:
    """Parse a dotted/indexed state path such as ``nodes['x'].output.ok``."""
    segments: list[Union[str, int]] = [tokens.next()[1]]
    while True:
        if tokens.accept("."):
            kind, text = tokens.next()
            if kind != "ident":
                raise ExpressionError(f"expected identifier after '.' but found {text!r}")
            segments.append(text)
        elif tokens.accept("["):
            kind, text = tokens.next()
            if kind == "string":
                segments.append(text[1:-1])
            elif kind == "number" and "." not in text:
                segments.append(int(text))
            else:
                raise ExpressionError(f"invalid subscript {text!r} in path expression")
            tokens.expect("]")
        else:
            return _Path(segments=tuple(segments))


def _peek_keyword(tokens: _Tokenizer) -> str | None:
    """Return the next token text when it is a boolean keyword."""
    token = tokens.peek()
    if token is not None and token[0] == "ident" and token[1] in {"and", "or", "not"}:
        return token[1]
    return None


def _collect_paths(node: _Node, found: set[tuple[str, ...]]) -> None:
    """Accumulate the string-prefix of every path referenced under ``node``."""
    if isinstance(node, _Path):
        prefix: list[str] = []
        for segment in node.segments:
            if isinstance(segment, int):
                break
            prefix.append(segment)
        found.add(tuple(prefix))
    elif isinstance(node, (_Compare, _BoolOp)):
        _collect_paths(node.left, found)
        _collect_paths(node.right, found)
    elif isinstance(node, _Not):
        _collect_paths(node.operand, found)


def _resolve_path(path: _Path, state: Mapping[str, Any]) -> Any:
    """Resolve a path against the state document.

    Missing keys resolve to ``None`` so predicates can test optional fields.

    Args:
        path: Parsed path to resolve.
        state: State document to look values up in.

    Returns:
        The referenced value, or ``None`` when any segment is missing.
    """
    current: Any = state
    for segment in path.segments:
        if isinstance(segment, int):
            if isinstance(current, (list, tuple)) and -len(current) <= segment < len(current):
                current = current[segment]
            else:
                return None
        elif isinstance(current, Mapping) and segment in current:
            current = current[segment]
        else:
            return None
    return current


def _evaluate_node(node: _Node, state: Mapping[str, Any]) -> Any:
    """Evaluate an AST node against the state document."""
    if isinstance(node, _Literal):
        return node.value
    if isinstance(node, _Path):
        return _resolve_path(node, state)
    if isinstance(node, _Not):
        return not _truthy(_evaluate_node(node.operand, state))
    if isinstance(node, _BoolOp):
        left = _truthy(_evaluate_node(node.left, state))
        if node.op == "and":
            return left and _truthy(_evaluate_node(node.right, state))
        return left or _truthy(_evaluate_node(node.right, state))
    left_value = _evaluate_node(node.left, state)
    right_value = _evaluate_node(node.right, state)
    if node.op == "==":
        return left_value == right_value
    if node.op == "!=":
        return left_value != right_value
    if not isinstance(left_value, (int, float)) or not isinstance(right_value, (int, float)):
        raise ExpressionError(
            f"ordering comparison {node.op!r} requires numbers, "
            f"got {type(left_value).__name__} and {type(right_value).__name__}"
        )
    if node.op == "<":
        return left_value < right_value
    if node.op == "<=":
        return left_value <= right_value
    if node.op == ">":
        return left_value > right_value
    return left_value >= right_value


def _truthy(value: Any) -> bool:
    """Return the boolean interpretation used by ``and``/``or``/``not``."""
    return bool(value)


def evaluate_expression(
    expression: CompiledExpression | str, state: Mapping[str, Any]
) -> Any:
    """Evaluate an expression against a state document.

    Args:
        expression: A compiled expression or raw expression text.
        state: State document (e.g. ``{"flow": ..., "nodes": ...}``).

    Returns:
        The expression's value; predicates return booleans.

    Raises:
        ExpressionError: If the expression is invalid or applies an ordering
            comparison to non-numeric operands.
    """
    compiled = (
        expression
        if isinstance(expression, CompiledExpression)
        else compile_expression(expression)
    )
    return _evaluate_node(compiled.root, state)


def render_template(value: Any, state: Mapping[str, Any]) -> Any:
    """Render a manifest binding value against the run state.

    Strings that are exactly one ``{{ expr }}`` template return the evaluated
    value with its original type. Strings with embedded templates interpolate
    each evaluated value into the text. Mappings and lists render recursively;
    all other values pass through unchanged.

    Args:
        value: Binding value from the manifest.
        state: State document to evaluate templates against.

    Returns:
        The rendered value.

    Raises:
        ExpressionError: If an embedded expression is invalid.
    """
    if isinstance(value, str):
        match = _TEMPLATE_RE.fullmatch(value.strip())
        if match is not None:
            return evaluate_expression(match.group(1), state)
        return _TEMPLATE_RE.sub(
            lambda m: str(evaluate_expression(m.group(1), state)), value
        )
    if isinstance(value, Mapping):
        return {key: render_template(item, state) for key, item in value.items()}
    if isinstance(value, list):
        return [render_template(item, state) for item in value]
    return value


def extract_template_paths(value: Any) -> set[tuple[str, ...]]:
    """Collect state paths referenced by every template embedded in ``value``.

    Args:
        value: Binding value from the manifest (string, mapping, list, or scalar).

    Returns:
        A set of referenced path prefixes (string segments only).

    Raises:
        ExpressionError: If an embedded expression is invalid.
    """
    found: set[tuple[str, ...]] = set()
    if isinstance(value, str):
        for match in _TEMPLATE_RE.finditer(value):
            found |= compile_expression(match.group(1)).paths()
    elif isinstance(value, Mapping):
        for item in value.values():
            found |= extract_template_paths(item)
    elif isinstance(value, list):
        for item in value:
            found |= extract_template_paths(item)
    return found


__all__ = [
    "CompiledExpression",
    "ExpressionError",
    "compile_expression",
    "evaluate_expression",
    "extract_template_paths",
    "render_template",
]
