"""Bounded recursive redaction for every Operator projection family."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import islice
from typing import Final

from fdai_service_contracts import JsonObject, JsonValue

MAX_REDACTION_DEPTH: Final = 12
MAX_REDACTION_ITEMS: Final = 500
REDACTED: Final = "[REDACTED]"
_SENSITIVE_ALIASES: Final = frozenset(
    {
        "accesskey",
        "accesstoken",
        "apikey",
        "authorization",
        "bearer",
        "clientsecret",
        "connectionstring",
        "cookie",
        "credential",
        "endpoint",
        "password",
        "privatekey",
        "refreshtoken",
        "sas",
        "sastoken",
        "secret",
        "sharedkey",
        "token",
    }
)
_SENSITIVE_SUFFIXES: Final = (
    "accesskey",
    "accesstoken",
    "apikey",
    "clientsecret",
    "connectionstring",
    "credential",
    "password",
    "privatekey",
    "refreshtoken",
    "sastoken",
    "secret",
    "sharedkey",
    "token",
)


def redact_projection(value: object, *, depth: int = 0) -> JsonValue:
    """Return bounded JSON while replacing credential-bearing alias fields."""
    if depth >= MAX_REDACTION_DEPTH:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED
            if _sensitive_key(str(key))
            else redact_projection(item, depth=depth + 1)
            for key, item in islice(value.items(), MAX_REDACTION_ITEMS)
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            redact_projection(item, depth=depth + 1) for item in islice(value, MAX_REDACTION_ITEMS)
        ]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def redact_mapping(value: Mapping[str, object]) -> JsonObject:
    """Redact a mapping root while preserving its JSON-object shape."""
    redacted = redact_projection(value)
    if not isinstance(redacted, dict):
        raise TypeError("Operator projection root MUST remain an object")
    return redacted


def _sensitive_key(key: str) -> bool:
    compact = "".join(character for character in key.casefold() if character.isalnum())
    return compact in _SENSITIVE_ALIASES or compact.endswith(_SENSITIVE_SUFFIXES)


__all__ = [
    "MAX_REDACTION_DEPTH",
    "MAX_REDACTION_ITEMS",
    "REDACTED",
    "redact_mapping",
    "redact_projection",
]
