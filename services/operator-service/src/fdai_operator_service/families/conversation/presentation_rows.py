"""Project verified query rows into bounded operator-readable scalar fields."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

_LIFTED_ROW_FIELDS = ("name", "type", "status", "location")
_INTERNAL_ROW_FIELDS = frozenset(
    {
        "catalog_digest",
        "declaration_digest",
        "execution_authority",
        "revision",
        "type_version",
    }
)
_MAX_NESTED_DEPTH = 2


def readable_row(values: Mapping[str, object]) -> dict[str, object]:
    """Keep direct scalars and lift allowlisted leaves from bounded nested bags."""
    readable: dict[str, object] = {}
    for field, value in values.items():
        if not isinstance(field, str) or not field or isinstance(value, Mapping | list):
            continue
        readable[field] = value
    for bag in _nested_mappings(values, depth=_MAX_NESTED_DEPTH):
        for field in _LIFTED_ROW_FIELDS:
            candidate = bag.get(field)
            if candidate is None or isinstance(candidate, Mapping | list):
                continue
            readable.setdefault(field, candidate)
    return readable


def ordered_columns(fields: Sequence[str]) -> list[str]:
    """Lead with readable resource fields and keep opaque identity afterward."""
    readable = [field for field in fields if field not in _INTERNAL_ROW_FIELDS]
    selected = readable or list(fields)
    leading = [field for field in _LIFTED_ROW_FIELDS if field in selected]
    return leading + [field for field in selected if field not in leading]


def _nested_mappings(
    values: Mapping[str, object],
    *,
    depth: int,
) -> Iterator[Mapping[str, object]]:
    if depth <= 0:
        return
    for value in values.values():
        if not isinstance(value, Mapping):
            continue
        yield value
        yield from _nested_mappings(value, depth=depth - 1)


__all__ = ["ordered_columns", "readable_row"]
