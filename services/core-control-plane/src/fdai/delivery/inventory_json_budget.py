"""Reject oversized JSON-shaped records before dataclass copies or whole-string encoding."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from json.encoder import encode_basestring_ascii

_STRING_CHUNK_CHARACTERS = 1024


def inventory_json_exceeds_budget(value: object, *, maximum_bytes: int) -> bool:
    """Preflight a lower bound; the existing encoder still owns exact byte accounting.

    Walk dataclass fields without copying their containers. Count JSON strings in
    bounded pieces, including ASCII escaping. Numeric and ``default=str`` leaves
    retain conservative lower bounds rather than materializing their representation.
    """
    size = 0
    for amount in _minimum_json_sizes(value):
        size += amount
        if size > maximum_bytes:
            return True
    return False


def _minimum_json_sizes(value: object) -> Iterator[int]:
    if isinstance(value, str):
        yield len(value) + 2
        for offset in range(0, len(value), _STRING_CHUNK_CHARACTERS):
            chunk = value[offset : offset + _STRING_CHUNK_CHARACTERS]
            yield len(encode_basestring_ascii(chunk)) - len(chunk) - 2
    elif is_dataclass(value) and not isinstance(value, type):
        yield 2
        for index, field in enumerate(fields(value)):
            if index:
                yield 1
            yield from _minimum_json_sizes(field.name)
            yield 1
            yield from _minimum_json_sizes(getattr(value, field.name))
    elif isinstance(value, dict):
        yield 2
        for index, (key, item) in enumerate(value.items()):
            if index:
                yield 1
            if isinstance(key, str):
                yield from _minimum_json_sizes(key)
            else:
                yield 2
            yield 1
            yield from _minimum_json_sizes(item)
    elif isinstance(value, (list, tuple)):
        yield 2
        for index, item in enumerate(value):
            if index:
                yield 1
            yield from _minimum_json_sizes(item)
    elif value is None or isinstance(value, bool):
        yield 4 if value is None or value else 5
    else:
        yield 1
