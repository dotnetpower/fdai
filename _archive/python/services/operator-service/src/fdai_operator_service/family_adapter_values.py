"""Shared value normalization for Operator family adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast


def mapping(value: object) -> Mapping[str, object]:
    normalized = json.loads(json.dumps(value, default=str))
    if not isinstance(normalized, dict):
        raise ValueError("proposal payload MUST serialize to a JSON object")
    return cast(Mapping[str, object], normalized)
