"""Strict primitive decoders for the detection governance policy."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SEMANTIC_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")


class DetectionGovernancePolicyError(ValueError):
    """The detector governance policy is absent, malformed, or unsafe."""


def policy_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DetectionGovernancePolicyError(f"{label} MUST be an object")
    return value


def policy_array(value: object, label: str, *, maximum: int = 64) -> list[object]:
    if not isinstance(value, list) or not value:
        raise DetectionGovernancePolicyError(f"{label} MUST be a non-empty array")
    if len(value) > maximum:
        raise DetectionGovernancePolicyError(f"{label} MUST contain at most {maximum} items")
    return value


def require_exact_keys(value: Mapping[str, Any], label: str, expected: set[str]) -> None:
    if set(value) != expected:
        raise DetectionGovernancePolicyError(f"{label} fields do not match the governed schema")


def policy_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise DetectionGovernancePolicyError(f"{label} MUST be bounded non-empty text")
    return value


def policy_identifier(value: object, label: str) -> str:
    text = policy_text(value, label)
    if _IDENTIFIER.fullmatch(text) is None:
        raise DetectionGovernancePolicyError(f"{label} MUST be a canonical identifier")
    return text


def policy_version(value: object, label: str) -> str:
    text = policy_text(value, label)
    if _SEMANTIC_VERSION.fullmatch(text) is None:
        raise DetectionGovernancePolicyError(f"{label} MUST be a semantic version")
    return text


def policy_integer(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise DetectionGovernancePolicyError(f"{label} MUST be in [{minimum}, {maximum}]")
    return value


def policy_ratio(
    value: object,
    label: str,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise DetectionGovernancePolicyError(f"{label} MUST be in [{minimum}, {maximum}]")
    return float(value)


def policy_member(value: object, label: str, *, allowed: frozenset[str]) -> str:
    text = policy_text(value, label)
    if text not in allowed:
        raise DetectionGovernancePolicyError(f"{label} is unsupported")
    return text


def policy_boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise DetectionGovernancePolicyError(f"{label} MUST be boolean")
    return value


def require_unique(values: Iterable[str], *, label: str) -> None:
    items = tuple(values)
    if not items or len(items) != len(set(items)):
        raise DetectionGovernancePolicyError(f"{label} identifiers MUST be non-empty and unique")


__all__ = [
    "DetectionGovernancePolicyError",
    "policy_array",
    "policy_boolean",
    "policy_identifier",
    "policy_integer",
    "policy_mapping",
    "policy_member",
    "policy_ratio",
    "policy_text",
    "policy_version",
    "require_exact_keys",
    "require_unique",
]
