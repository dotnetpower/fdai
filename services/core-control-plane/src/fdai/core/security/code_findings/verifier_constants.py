"""Bounded constant evaluation for the Python weakness verifier.

The verifier folds only conditions whose value is fixed by the source: literals and function-local
names bound exactly once to an immutable literal expression. Anything else is ``UNKNOWN`` and the
verifier keeps analyzing every branch. Evaluation never imports, executes, or calls source code.
"""

from __future__ import annotations

import ast
import operator
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

UNKNOWN: Final = object()
_MAX_STRING = 4096
_MAX_INT = 2**63
_SCALARS = (bool, int, float, str, bytes, type(None))
_BINARY: Mapping[type[ast.operator], Callable[[Any, Any], object]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_COMPARE: Mapping[type[ast.cmpop], Callable[[Any, Any], object]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: operator.contains(right, left),
    ast.NotIn: lambda left, right: not operator.contains(right, left),
}


def _bounded(value: object) -> object:
    if isinstance(value, str | bytes | tuple) and len(value) > _MAX_STRING:
        return UNKNOWN
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > _MAX_INT:
        return UNKNOWN
    return value


def _oversized_repeat(left: object, right: object) -> bool:
    for sequence, count in ((left, right), (right, left)):
        if isinstance(sequence, str | bytes | tuple) and isinstance(count, int):
            return count * max(len(sequence), 1) > _MAX_STRING
    return False


def _index(node: ast.expr, constants: Mapping[str, object]) -> object:
    if not isinstance(node, ast.Slice):
        value = evaluate(node, constants)
        return value if isinstance(value, int) and not isinstance(value, bool) else UNKNOWN
    parts = [
        None if part is None else evaluate(part, constants)
        for part in (node.lower, node.upper, node.step)
    ]
    if any(part is not None and not isinstance(part, int) for part in parts):
        return UNKNOWN
    return slice(*parts)


def evaluate(node: ast.expr, constants: Mapping[str, object]) -> object:  # noqa: PLR0911
    """Return the fixed value of ``node`` or ``UNKNOWN``."""
    try:
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, _SCALARS) else UNKNOWN
        if isinstance(node, ast.Name):
            return constants.get(node.id, UNKNOWN)
        if isinstance(node, ast.Tuple):
            items = tuple(evaluate(item, constants) for item in node.elts)
            return UNKNOWN if UNKNOWN in items else _bounded(items)
        if isinstance(node, ast.UnaryOp):
            operand = evaluate(node.operand, constants)
            if operand is UNKNOWN:
                return UNKNOWN
            if isinstance(node.op, ast.Not):
                return not operand
            if isinstance(node.op, ast.USub) and isinstance(operand, int | float):
                return -operand
            return (
                operand
                if isinstance(node.op, ast.UAdd) and isinstance(operand, int | float)
                else UNKNOWN
            )
        if isinstance(node, ast.BinOp):
            function = _BINARY.get(type(node.op))
            left, right = evaluate(node.left, constants), evaluate(node.right, constants)
            if function is None or UNKNOWN in (left, right):
                return UNKNOWN
            if isinstance(node.op, ast.Mult) and _oversized_repeat(left, right):
                return UNKNOWN
            return _bounded(function(left, right))
        if isinstance(node, ast.BoolOp):
            result: object = UNKNOWN
            for item in node.values:
                result = evaluate(item, constants)
                if result is UNKNOWN:
                    return UNKNOWN
                if bool(result) is isinstance(node.op, ast.Or):
                    return result
            return result
        if isinstance(node, ast.Compare):
            left = evaluate(node.left, constants)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                function = _COMPARE.get(type(op))
                right = evaluate(comparator, constants)
                if function is None or UNKNOWN in (left, right):
                    return UNKNOWN
                if not function(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Subscript):
            value, index = evaluate(node.value, constants), _index(node.slice, constants)
            if not isinstance(value, str | bytes | tuple) or index is UNKNOWN:
                return UNKNOWN
            return value[index]  # type: ignore[index,call-overload]
    except (ArithmeticError, IndexError, TypeError, ValueError):
        return UNKNOWN
    return UNKNOWN


def single_assignment_constants(
    function: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> dict[str, object]:
    """Return function-local names bound exactly once, by plain assignment, to a fixed value."""
    if function is None:
        return {}
    bindings: Counter[str] = Counter()
    candidates: dict[str, ast.expr] = {}
    excluded = {arg.arg for arg in ast.walk(function.args) if isinstance(arg, ast.arg)}
    for node in (item for statement in function.body for item in ast.walk(statement)):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            bindings[node.id] += 1
        elif isinstance(node, ast.Global | ast.Nonlocal):
            excluded.update(node.names)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            excluded.add(node.name)
        elif isinstance(node, ast.alias):
            excluded.add((node.asname or node.name).split(".", 1)[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            excluded.add(node.name)
        elif isinstance(node, ast.MatchAs | ast.MatchStar) and node.name:
            excluded.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            excluded.add(node.rest)
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            candidates[node.targets[0].id] = node.value
    pending = {
        name: value
        for name, value in candidates.items()
        if bindings[name] == 1 and name not in excluded
    }
    constants: dict[str, object] = {}
    progressed = True
    while progressed:
        progressed = False
        for name, value in list(pending.items()):
            folded = evaluate(value, constants)
            if folded is not UNKNOWN:
                constants[name] = folded
                del pending[name]
                progressed = True
    return constants


def _pattern(pattern: ast.pattern, subject: object) -> bool | None:
    if isinstance(pattern, ast.MatchValue):
        value = evaluate(pattern.value, {})
        return None if value is UNKNOWN else bool(value == subject)
    if isinstance(pattern, ast.MatchSingleton):
        return pattern.value is subject
    if isinstance(pattern, ast.MatchAs):
        return True if pattern.pattern is None else _pattern(pattern.pattern, subject)
    if isinstance(pattern, ast.MatchOr):
        results = [_pattern(item, subject) for item in pattern.patterns]
        if True in results:
            return True
        return None if None in results else False
    return None


def selected_case(
    subject: ast.expr, cases: Sequence[ast.match_case], constants: Mapping[str, object]
) -> int | None:
    """Return the index of the case a fixed subject selects, ``-1`` for none, else ``None``."""
    value = evaluate(subject, constants)
    if value is UNKNOWN:
        return None
    for index, case in enumerate(cases):
        matched = _pattern(case.pattern, value)
        if matched is None or (matched and case.guard is not None):
            return None
        if matched:
            return index
    return -1


def irrefutable(cases: Sequence[ast.match_case]) -> bool:
    """Return whether one unguarded case always matches."""
    return any(
        case.guard is None
        and isinstance(case.pattern, ast.MatchAs)
        and case.pattern.pattern is None
        for case in cases
    )
