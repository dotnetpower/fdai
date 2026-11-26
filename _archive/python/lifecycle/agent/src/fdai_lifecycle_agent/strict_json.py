"""Bounded reads and strict JSON decoding shared by every agent input boundary."""

from __future__ import annotations

import json
from pathlib import Path


def read_limited(path: Path, *, limit: int, label: str) -> bytes:
    """Read at most ``limit`` bytes. ``OSError`` propagates; a larger file raises ``ValueError``."""

    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{label} exceeds the size limit")
    return data


def load_json(raw: bytes, *, label: str) -> object:
    """Decode UTF-8 JSON and reject duplicate keys and non-finite numbers.

    The bytes are decoded as UTF-8 first, because ``json.loads`` would also accept UTF-16 and
    UTF-32 input.
    """

    try:
        text = raw.decode("utf-8")
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise ValueError(f"{label} MUST be strict UTF-8 JSON") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError("non-finite number")
