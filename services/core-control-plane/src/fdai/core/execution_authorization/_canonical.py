"""Canonical digest helper for execution-authorization assembly."""

from __future__ import annotations

import hashlib
import json


def canonical_digest(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["canonical_digest"]
