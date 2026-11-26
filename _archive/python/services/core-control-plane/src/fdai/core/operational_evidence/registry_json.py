"""Strict, content-addressed loading shared by the reviewed evidence registries."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

_MAX_REGISTRY_BYTES = 256 * 1024


class RegistryUnavailableError(ValueError):
    """A registry revision cannot be trusted as a whole; every dependent purpose is unavailable."""


class RevisionClass(StrEnum):
    """Content-derived relation between two consecutive registry revisions."""

    ROUTINE_ROTATION = "routine_rotation"
    REVOCATION = "revocation"


class _TrackedDict(dict[str, Any]):
    """A parsed JSON object that remembers keys that appeared more than once."""

    duplicates: tuple[str, ...] = ()


def _pairs(pairs: list[tuple[str, Any]]) -> _TrackedDict:
    value = _TrackedDict()
    duplicates: list[str] = []
    for key, item in pairs:
        if key in value:
            duplicates.append(key)
        value[key] = item
    value.duplicates = tuple(sorted(set(duplicates)))
    return value


def content_pin(data: bytes) -> str:
    """Return the content address of the exact reviewed bytes."""

    return "sha256:" + hashlib.sha256(data).hexdigest()


def load_pinned_json(data: bytes, *, expected_pin: str, label: str) -> Mapping[str, Any]:
    """Parse bounded JSON bytes only when they match the out-of-band reviewed pin."""

    if not isinstance(data, bytes) or len(data) > _MAX_REGISTRY_BYTES:
        raise RegistryUnavailableError(f"{label} MUST be bounded bytes")
    if content_pin(data) != expected_pin:
        raise RegistryUnavailableError(f"{label} content does not match its reviewed pin")
    try:
        parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryUnavailableError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(parsed, _TrackedDict):
        raise RegistryUnavailableError(f"{label} MUST be a JSON object")
    return parsed


def load_strict_json_text(text: str, *, label: str) -> Mapping[str, Any]:
    """Parse deployment-supplied JSON text; any repeated key anywhere makes it unavailable."""

    if not isinstance(text, str) or len(text) > _MAX_REGISTRY_BYTES:
        raise RegistryUnavailableError(f"{label} MUST be bounded text")
    try:
        parsed = json.loads(text, object_pairs_hook=_pairs)
    except json.JSONDecodeError as exc:
        raise RegistryUnavailableError(f"{label} is not valid JSON") from exc
    if not isinstance(parsed, _TrackedDict):
        raise RegistryUnavailableError(f"{label} MUST be a JSON object")
    if has_duplicates(parsed):
        raise RegistryUnavailableError(f"{label} repeats a key")
    return parsed


def has_duplicates(value: object) -> bool:
    """Return whether any object in a parsed subtree repeated one of its keys."""

    if isinstance(value, _TrackedDict):
        return bool(value.duplicates) or any(has_duplicates(item) for item in value.values())
    if isinstance(value, list):
        return any(has_duplicates(item) for item in value)
    return False


def exact_fields(value: object, required: frozenset[str], *, label: str) -> Mapping[str, Any]:
    """Return an object with exactly the declared fields and no repeated key."""

    if not isinstance(value, Mapping):
        raise ValueError(f"{label} MUST be an object")
    if isinstance(value, _TrackedDict) and value.duplicates:
        raise ValueError(f"{label} repeats a key")
    if set(value) != required:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def bounded_text(value: object, *, label: str, maximum: int = 512) -> str:
    """Return one bounded, non-empty identifier-like string."""

    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} MUST be bounded non-empty text")
    if any(character in value for character in "\r\n\x00"):
        raise ValueError(f"{label} MUST NOT contain control characters")
    return value


def text_tuple(value: object, *, label: str, maximum: int = 64) -> tuple[str, ...]:
    """Return a unique, ordered tuple of bounded strings."""

    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{label} MUST be a bounded non-empty array")
    items = tuple(bounded_text(item, label=label) for item in value)
    if len(set(items)) != len(items):
        raise ValueError(f"{label} MUST NOT repeat values")
    return tuple(sorted(items))


def aware_time(value: object, *, label: str) -> datetime:
    """Parse one timezone-aware ISO 8601 instant."""

    text = bounded_text(value, label=label, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} MUST be an ISO 8601 instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} MUST include a timezone")
    return parsed.astimezone(UTC)


def strict_bool(value: object, *, label: str) -> bool:
    """Return a JSON boolean without coercing other values."""

    if type(value) is not bool:
        raise ValueError(f"{label} MUST be a boolean")
    return value


def positive_int(value: object, *, label: str, maximum: int) -> int:
    """Return a bounded positive JSON integer without coercing booleans."""

    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{label} MUST be an integer in [1, {maximum}]")
    return value


@dataclass(frozen=True, slots=True)
class ValidityWindow:
    """Reviewed validity of one binding, grant, or scope."""

    valid_from: datetime
    valid_until: datetime
    revoked: bool

    def __post_init__(self) -> None:
        if self.valid_until <= self.valid_from:
            raise ValueError("registry validity MUST end after it starts")

    def active_at(self, evaluated_at: datetime) -> bool:
        """Return whether the entry is unrevoked and inside its reviewed window."""

        return not self.revoked and self.valid_from <= evaluated_at < self.valid_until

    def narrowed_by(self, current: ValidityWindow) -> bool:
        """Return whether a later revision revoked or shortened this window."""

        return (
            (current.revoked and not self.revoked)
            or current.valid_from > self.valid_from
            or current.valid_until < self.valid_until
        )


def validity(raw: Mapping[str, Any], *, label: str) -> ValidityWindow:
    """Parse the shared valid_from, valid_until, and revoked fields."""

    return ValidityWindow(
        valid_from=aware_time(raw["valid_from"], label=f"{label}.valid_from"),
        valid_until=aware_time(raw["valid_until"], label=f"{label}.valid_until"),
        revoked=strict_bool(raw["revoked"], label=f"{label}.revoked"),
    )


__all__ = [
    "RegistryUnavailableError",
    "RevisionClass",
    "ValidityWindow",
    "aware_time",
    "bounded_text",
    "content_pin",
    "exact_fields",
    "has_duplicates",
    "load_pinned_json",
    "load_strict_json_text",
    "positive_int",
    "strict_bool",
    "text_tuple",
    "validity",
]
