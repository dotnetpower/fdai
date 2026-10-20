"""Reject oversized JSON-shaped records before dataclass copies or whole-string encoding."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from json.encoder import encode_basestring_ascii

_STRING_CHUNK_CHARACTERS = 1024
_MAX_JSON_PREFLIGHT_DEPTH = 64


def inventory_json_exceeds_budget(value: object, *, maximum_bytes: int) -> bool:
    """Preflight a lower bound; the existing encoder still owns exact byte accounting.

    Walk dataclass fields without copying their containers. Count JSON strings in
    bounded pieces, including ASCII escaping. Known scalar representations stay
    bounded; large integers and unknown ``default=str`` leaves retain lower bounds.
    """
    size = 0
    for amount in _minimum_json_sizes(value):
        size += amount
        if size > maximum_bytes:
            return True
    return False


def _minimum_json_sizes(value: object, *, depth: int = 0) -> Iterator[int]:
    if depth > _MAX_JSON_PREFLIGHT_DEPTH:
        raise ValueError("inventory JSON exceeds maximum preflight nesting depth")
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
            yield from _minimum_json_sizes(field.name, depth=depth + 1)
            yield 1
            yield from _minimum_json_sizes(getattr(value, field.name), depth=depth + 1)
    elif isinstance(value, Mapping):
        yield 2
        for index, (key, item) in enumerate(value.items()):
            if index:
                yield 1
            if isinstance(key, str):
                yield from _minimum_json_sizes(key, depth=depth + 1)
            else:
                yield 2
            yield 1
            yield from _minimum_json_sizes(item, depth=depth + 1)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        # Reserve each child's one-byte minimum before iteration, then subtract that charge.
        yield max(2, 2 * len(value) + 1)
        for item in value:
            amounts = _minimum_json_sizes(item, depth=depth + 1)
            yield next(amounts) - 1
            yield from amounts
    elif value is None or isinstance(value, bool):
        yield 4 if value is None or value else 5
    elif isinstance(value, int):
        bits = int.bit_length(value)
        if bits <= 4096:
            yield len(int.__repr__(value))
        else:
            # A lower approximation of log10(2) avoids constructing enormous decimal strings.
            yield ((bits - 1) * 30102 // 100000 + 1) + int(value < 0)
    elif isinstance(value, float):
        yield len(float.__repr__(value))
    elif isinstance(value, datetime):
        encoded = (
            value.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if value.tzinfo is not None
            else value.isoformat()
        )
        yield len(encoded) + 2
    else:
        yield 1
