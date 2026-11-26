"""Primitive validation shared by adaptive telemetry evidence contracts."""

from __future__ import annotations

from datetime import datetime


def bounded_text(name: str, value: object, *, maximum: int = 256) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or not value.isprintable()
    ):
        raise ValueError(f"{name} MUST be a non-empty string of at most {maximum} characters")


def sha256_digest(name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in value[7:])
    ):
        raise ValueError(f"{name} MUST be a sha256 digest")


def aware_datetime(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def bounded_int(name: str, value: object, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} MUST be an integer in [{minimum}, {maximum}]")


def no_authority(value: object) -> None:
    for name in ("execution_authority", "mutation_authority", "query_execution_authority"):
        if getattr(value, name, None) is not False:
            raise ValueError(f"{name} MUST remain false")


__all__ = [
    "aware_datetime",
    "bounded_int",
    "bounded_text",
    "no_authority",
    "sha256_digest",
]
