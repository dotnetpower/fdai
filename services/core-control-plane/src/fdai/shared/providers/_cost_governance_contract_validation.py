"""Shared validation helpers for Cost Governance contracts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_MAX_REFS = 64


def _text(name: str, value: str) -> None:
    if not value or len(value) > 512:
        raise ValueError(f"{name} MUST be non-empty and bounded")


def _identifier(name: str, value: str) -> None:
    if len(value) > 256 or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a canonical identifier")


def _digest(name: str, value: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a SHA-256 digest")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _refs(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(values))
    if not 1 <= len(normalized) <= _MAX_REFS:
        raise ValueError(f"{name} MUST contain 1..{_MAX_REFS} unique references")
    for value in normalized:
        _text(name, value)
    return normalized


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")
