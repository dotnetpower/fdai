"""Stable durable identities for Mimir operational catalog reviews."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

STATE_PREFIX = "pantheon/mimir/catalog-review"
RECORD_KIND = "mimir_operational_catalog_review"


def state_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"{STATE_PREFIX}/{digest}"


def idempotency_key(candidate: Mapping[str, Any]) -> str:
    value = candidate.get("idempotency_key")
    if not isinstance(value, str) or not value:
        raise ValueError("catalog review candidate requires an idempotency_key")
    return value


def required_digest(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Mimir catalog review {field} is invalid")
    return value


def validate_identity(
    record: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    candidate_digest: str,
    package_digest: str,
) -> None:
    if (
        record.get("kind") != RECORD_KIND
        or record.get("idempotency_key") != idempotency_key(candidate)
        or required_digest(record, "candidate_digest") != candidate_digest
        or required_digest(record, "package_digest") != package_digest
    ):
        raise ValueError("Mimir catalog review durable identity conflict")
    if record.get("status") == "pending" and record.get("candidate") != dict(candidate):
        raise ValueError("Mimir catalog review durable candidate conflict")


__all__ = [
    "RECORD_KIND",
    "STATE_PREFIX",
    "idempotency_key",
    "required_digest",
    "state_key",
    "validate_identity",
]
