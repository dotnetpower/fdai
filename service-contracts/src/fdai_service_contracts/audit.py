"""Canonical audit serialization shared by independent service writers."""

import hashlib
import json
from collections.abc import Mapping

AUDIT_GENESIS_HASH = "0" * 64
AUDIT_APPEND_LOCK_KEY = 0x0FDA10AAAAAA01


def canonical_audit_entry(entry: Mapping[str, object]) -> str:
    """Serialize an audit entry to the exact bytes used by the hash chain."""
    return json.dumps(dict(entry), sort_keys=True, separators=(",", ":"), default=str)


def next_audit_hash(previous: str, entry: Mapping[str, object]) -> str:
    """Chain one canonical entry onto the previous audit digest."""
    return hashlib.sha256((previous + canonical_audit_entry(entry)).encode()).hexdigest()
