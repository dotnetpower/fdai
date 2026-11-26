"""Canonical validation and digest helpers for safeguard dispatch evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from fdai_service_contracts.execution_safeguards import SafeguardProofBundle
from fdai_service_contracts.ontology_query import content_digest

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def validate_text(name: str, value: str) -> None:
    """Require one canonical bounded evidence identity."""

    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 512:
        raise ValueError(f"safeguard dispatch evidence {name} MUST be canonical")


def validate_digest(name: str, value: str) -> None:
    """Require one canonical SHA-256 digest."""

    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"safeguard dispatch evidence {name} MUST be SHA-256")


def utc(value: datetime, name: str) -> datetime:
    """Normalize one timezone-aware datetime to UTC."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"safeguard dispatch evidence {name} MUST include a timezone")
    return value.astimezone(UTC)


def validate_utc(name: str, value: datetime) -> None:
    """Require an exact built-in UTC datetime."""

    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError(f"safeguard dispatch evidence {name} MUST be normalized to UTC")


def payload_digest(
    payload: Mapping[str, object],
    domain: str,
    *,
    digest_field: str,
) -> str:
    """Hash one domain-separated payload after canonical value normalization."""

    body = dict(payload)
    body.pop(digest_field, None)
    return content_digest({"domain": domain, "body": _normalize(body)})


def _normalize(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, SafeguardProofBundle):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(cast(Any, value)))
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


__all__ = [
    "payload_digest",
    "utc",
    "validate_digest",
    "validate_text",
    "validate_utc",
]
