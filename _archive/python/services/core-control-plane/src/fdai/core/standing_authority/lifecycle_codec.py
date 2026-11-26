"""Canonical encoding shared by A3-E lifecycle records."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class AuthorizationLifecycleError(ValueError):
    """Raised when lifecycle state cannot safely advance or replay."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def instant(value: datetime) -> str:
    return aware_utc(value).isoformat().replace("+00:00", "Z")


def aware_utc(value: datetime) -> datetime:
    require_aware("timestamp", value)
    return value.astimezone(UTC)


def require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuthorizationLifecycleError(f"{name} MUST be timezone-aware")


def require_text(name: str, value: str) -> None:
    if not value.strip() or len(value) > 512:
        raise AuthorizationLifecycleError(f"{name} MUST be bounded non-empty text")


def require_digest(name: str, value: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise AuthorizationLifecycleError(f"{name} MUST be a sha256 digest")


__all__ = [
    "AuthorizationLifecycleError",
    "aware_utc",
    "canonical_json",
    "content_digest",
    "instant",
    "require_aware",
    "require_digest",
    "require_text",
]
