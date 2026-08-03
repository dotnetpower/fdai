"""Shared bounded validation helpers for ontology council contracts."""

from __future__ import annotations

import re
from collections.abc import Iterable

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,199}$")
_PROPERTY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def require_bounded(value: str, label: str, *, maximum: int = 128) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} MUST be bounded and non-empty")


def require_digest(value: str, label: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} MUST be a lowercase SHA-256 digest")


def require_identifier(value: str, label: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")


def require_property_names(values: tuple[str, ...]) -> None:
    if len(values) > 64 or len(values) != len(set(values)) or values != tuple(sorted(values)):
        raise ValueError("property names MUST be unique, sorted, and bounded")
    if any(_PROPERTY.fullmatch(value) is None for value in values):
        raise ValueError("property names MUST use the bounded property syntax")


def require_unique(values: Iterable[str], label: str) -> None:
    materialized: tuple[str, ...] = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} MUST be unique")


__all__ = [
    "require_bounded",
    "require_digest",
    "require_identifier",
    "require_property_names",
    "require_unique",
]
