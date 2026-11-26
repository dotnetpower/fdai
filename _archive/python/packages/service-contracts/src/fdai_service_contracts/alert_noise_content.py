"""Bounded canonical encoding for private alert evidence, not ontology query arguments."""

from __future__ import annotations

import hashlib
import json

MAX_ALERT_RECORD_BYTES = 8 * 1024 * 1024
MAX_ALERT_RECORD_NODES = 250_000
MAX_ALERT_RECORD_DEPTH = 32


def canonical_alert_json(value: object) -> str:
    """Encode strict JSON under finite alert-specific byte, node and depth ceilings.

    Smaller records retain the same sorted ASCII JSON bytes as ontology content digests.
    The separate budget admits organization-scale private evidence without widening the
    shared query contract. It never truncates records or grants evidence authority.
    """
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > MAX_ALERT_RECORD_DEPTH or count > MAX_ALERT_RECORD_NODES:
            raise ValueError("alert_record_bound_exceeded")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("alert_record_invalid")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in {str, bool, int, float}:
            raise ValueError("alert_record_invalid")
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    if len(encoded) > MAX_ALERT_RECORD_BYTES:
        raise ValueError("alert_record_bound_exceeded")
    return encoded


def digest_alert_payload(value: object) -> str:
    """Hash every bounded payload byte; the digest alone is not independent admission."""
    return "sha256:" + hashlib.sha256(canonical_alert_json(value).encode()).hexdigest()
