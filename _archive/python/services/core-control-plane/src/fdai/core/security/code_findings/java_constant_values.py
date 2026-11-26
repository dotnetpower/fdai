"""Bounded Java primitive constants, with Java integer promotion and overflow."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Constant:
    kind: str
    value: int | str | bool


def _wrap(value: int, kind: str) -> int:
    bits = 64 if kind == "long" else 32
    return (value + (1 << (bits - 1))) % (1 << bits) - (1 << (bits - 1))


def literal(text: str, kind: str) -> Constant | None:
    if kind in {"true", "false"}:
        return Constant("boolean", kind == "true")
    if kind in {"string_literal", "character_literal"}:
        raw = text if kind == "string_literal" else '"' + text[1:-1].replace('"', '\\"') + '"'
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(value, str) or len(value) > 4096:
            return None
        # Java chars are single UTF-16 code units, not arbitrary Python code points.
        if kind == "character_literal" and (len(value) != 1 or ord(value) > 0xFFFF):
            return None
        return Constant("char" if kind == "character_literal" else "String", value)
    if not kind.endswith("integer_literal"):
        return None
    cleaned = text.replace("_", "")
    numeric_kind = "long" if cleaned[-1:].lower() == "l" else "int"
    if numeric_kind == "long":
        cleaned = cleaned[:-1]
    base = (
        16
        if cleaned.lower().startswith("0x")
        else 2
        if cleaned.lower().startswith("0b")
        else 8
        if cleaned.startswith("0") and len(cleaned) > 1
        else 10
    )
    try:
        value = int(cleaned, base)
    except ValueError:
        return None
    bits = 64 if numeric_kind == "long" else 32
    if value >= 1 << (bits if base != 10 else bits - 1):
        return None
    return Constant(numeric_kind, _wrap(value, numeric_kind))


def coerce(value: Constant | None, kind: str) -> Constant | None:
    if value is None or kind == value.kind or kind == "var":
        return value
    if kind in {"int", "long", "byte", "short", "char"} and value.kind in {"int", "long", "char"}:
        integer = (
            ord(value.value)
            if value.kind == "char" and isinstance(value.value, str)
            else value.value
        )
        if not isinstance(integer, int) or isinstance(integer, bool):
            return None
        if kind == "long":
            return Constant("long", integer)
        if kind == "int" and value.kind != "long":
            return Constant("int", integer)
        lower, upper = {"byte": (-128, 127), "short": (-32768, 32767), "char": (0, 65535)}.get(
            kind, (1, 0)
        )
        if lower <= integer <= upper:
            return Constant("char", chr(integer)) if kind == "char" else Constant("int", integer)
    return None


def _number(value: Constant) -> tuple[int, str] | None:
    if value.kind == "char" and isinstance(value.value, str):
        return ord(value.value), "int"
    if value.kind in {"int", "long"} and isinstance(value.value, int):
        return value.value, value.kind
    return None


def unary(operator: str, value: Constant | None) -> Constant | None:
    if value is None:
        return None
    if operator == "!" and value.kind == "boolean":
        return Constant("boolean", not value.value)
    numeric = _number(value)
    if numeric is None:
        return None
    number, kind = numeric
    result = (
        number
        if operator == "+"
        else -number
        if operator == "-"
        else ~number
        if operator == "~"
        else None
    )
    return Constant(kind, _wrap(result, kind)) if result is not None else None


def binary(operator: str, left: Constant | None, right: Constant | None) -> Constant | None:
    if left is None or right is None:
        return None
    if operator == "+" and "String" in (left.kind, right.kind):

        def rendered(value: Constant) -> str:
            return str(value.value).lower() if value.kind == "boolean" else str(value.value)

        joined = rendered(left) + rendered(right)
        return Constant("String", joined) if len(joined) <= 4096 else None
    if left.kind == right.kind == "boolean":
        bool_a, bool_b = bool(left.value), bool(right.value)
        bool_operations = {
            "&&": bool_a and bool_b,
            "||": bool_a or bool_b,
            "&": bool_a & bool_b,
            "|": bool_a | bool_b,
            "^": bool_a ^ bool_b,
            "==": bool_a == bool_b,
            "!=": bool_a != bool_b,
        }
        return (
            Constant("boolean", bool_operations[operator]) if operator in bool_operations else None
        )
    a_number, b_number = _number(left), _number(right)
    if a_number is None or b_number is None:
        # String reference equality depends on interning and allocation; don't guess.
        return None
    a, a_kind = a_number
    b, b_kind = b_number
    kind = "long" if "long" in (a_kind, b_kind) else "int"
    comparisons = {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}
    if operator in comparisons:
        return Constant("boolean", comparisons[operator])
    if operator in {"/", "%"}:
        if b == 0:
            return None
        quotient = abs(a) // abs(b) * (-1 if (a < 0) != (b < 0) else 1)
        result = quotient if operator == "/" else a - quotient * b
    elif operator in {"<<", ">>", ">>>"}:
        kind = a_kind
        bits = 64 if kind == "long" else 32
        shift = b & (bits - 1)
        result = (
            a << shift
            if operator == "<<"
            else a >> shift
            if operator == ">>"
            else (a % (1 << bits)) >> shift
        )
    else:
        operations = {"+": a + b, "-": a - b, "*": a * b, "&": a & b, "|": a | b, "^": a ^ b}
        if operator not in operations:
            return None
        result = operations[operator]
    return Constant(kind, _wrap(result, kind))
