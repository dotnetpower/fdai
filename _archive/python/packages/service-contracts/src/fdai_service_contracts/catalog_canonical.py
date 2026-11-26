"""Canonical bytes, digest and signature-verifier type shared by every catalog verifier."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

SignatureVerifier = Callable[[str, bytes, bytes], bool]


def canonical_bytes(value: object) -> bytes:
    """Serialize one machine record with stable ordering."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_digest(value: object) -> str:
    """Return a lowercase SHA-256 over canonical JSON."""

    return hashlib.sha256(canonical_bytes(value)).hexdigest()
