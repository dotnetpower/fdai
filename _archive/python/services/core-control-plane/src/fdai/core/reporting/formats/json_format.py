"""JSON format encoder - the default, canonical FE contract."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.reporting.models import RenderedReport


class JsonFormatEncoder:
    """Serialize a :class:`RenderedReport` to compact UTF-8 JSON bytes.

    ``ensure_ascii=False`` keeps non-ASCII content (e.g. proper nouns)
    intact instead of escaping every character. The engine does not
    place user-controlled Hangul into an L0 audit surface (that stays
    English by policy), but a report title / label carrying non-ASCII
    proper nouns should not be double-encoded.

    Non-finite floats (``NaN`` / ``+-Inf``) that leak from a datasource
    into a widget payload are rewritten to ``null`` before encoding:
    RFC 8259 has no ``NaN`` / ``Infinity`` token, and Python's default
    ``json.dumps`` would emit those bare words, producing a body strict
    parsers (JS ``JSON.parse``, Go, Rust) reject. ``allow_nan=False`` is
    the hard backstop so a future non-finite value fails loudly in tests
    rather than shipping invalid JSON.
    """

    name = "json"
    content_type = "application/json"

    def encode(self, report: RenderedReport) -> bytes:
        payload = _sanitize(report.to_dict())
        return json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
            sort_keys=False,
            allow_nan=False,
        ).encode("utf-8")


def _sanitize(value: Any) -> Any:
    """Recursively replace non-finite floats with ``None`` for valid JSON."""
    # bool is an int subclass, not a float - it passes through untouched.
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, (str, bytes)):
        return value
    if isinstance(value, Sequence):
        return [_sanitize(item) for item in value]
    return value


__all__ = ["JsonFormatEncoder"]
