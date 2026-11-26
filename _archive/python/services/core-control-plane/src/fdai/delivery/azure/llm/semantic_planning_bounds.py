"""Input-size guards for Azure semantic planning."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

_MAX_CONTEXT_ITEMS = 8
_MAX_CONTEXT_CHARS = 12_000
_MAX_DESCRIPTORS = 512
_MAX_PROMPT_BYTES = 786_432


def bounded_input(
    payload: Mapping[str, Any],
    *,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    if len(context) > _MAX_CONTEXT_ITEMS or sum(len(item) for item in context) > _MAX_CONTEXT_CHARS:
        return False
    if len(descriptors) > _MAX_DESCRIPTORS:
        return False
    try:
        encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True).encode()
    except (TypeError, ValueError):
        return False
    return len(encoded) <= _MAX_PROMPT_BYTES


__all__ = ["bounded_input"]
