"""Canonical content identity for direction shadow generations and receipts."""

from __future__ import annotations

import hashlib
import json


def content_digest(value: object) -> str:
    """Return a SHA-256 identity over canonical JSON-compatible content."""

    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ["content_digest"]
