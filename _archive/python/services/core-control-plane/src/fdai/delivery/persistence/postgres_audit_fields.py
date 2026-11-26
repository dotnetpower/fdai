"""Canonical audit field helpers for the PostgreSQL state store."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai.shared.providers.audit_hash import canonical_entry


def audit_event_id(payload: Mapping[str, Any]) -> str:
    """Return an explicit UUID or a deterministic audit event identity."""

    raw = payload.get("event_id")
    if raw is not None:
        try:
            return str(UUID(str(raw)))
        except ValueError:
            pass
    identity = next(
        (
            str(payload[key])
            for key in ("idempotency_key", "correlation_id", "audit_id")
            if payload.get(key)
        ),
        canonical_entry(payload),
    )
    return str(uuid5(NAMESPACE_URL, f"fdai.audit://{identity}"))


def audit_actor(payload: Mapping[str, Any]) -> str:
    """Return the first normalized actor identity or the system actor."""

    for key in ("actor", "actor_oid", "producer_principal"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "fdai.system"


def audit_action_kind(payload: Mapping[str, Any]) -> str:
    """Return the first normalized action kind or the generic record kind."""

    for key in ("action_kind", "kind", "event_type"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "audit.record"


def incident_lock(incident_id: str) -> int:
    """Return a stable positive 63-bit per-incident advisory-lock key."""

    digest = hashlib.sha256(incident_id.encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) & ((1 << 63) - 1)


def json_object(value: object) -> Mapping[str, Any]:
    """Decode one stored JSON object or reject incompatible state."""

    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise RuntimeError("incident lifecycle audit entry is not a JSON object")
