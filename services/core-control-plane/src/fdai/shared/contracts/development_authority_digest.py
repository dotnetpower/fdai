"""Canonical digest and principal helpers for development-authority contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_authority_digest(value: Any) -> str:
    """Return a replay-stable SHA-256 digest for one JSON-compatible value."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def authority_text_digest(value: str) -> str:
    """Digest one exact authority-bearing text value without normalizing it."""

    return canonical_authority_digest({"value": value})


def normalized_principal(value: str) -> str:
    """Return the comparison form for authenticated principal references."""

    return value.strip().casefold()


def development_promotion_target_digest(
    *,
    action_type: str,
    action_type_version: str,
    action_type_digest: str,
    reviewed_replay_digest: str,
    source_revision: str,
    scenario_set_version: str,
    promotion_evidence_digest: str,
) -> str:
    """Bind an exact development promotion target to reviewed replay evidence."""

    return canonical_authority_digest(
        {
            "action_type": action_type,
            "action_type_version": action_type_version,
            "action_type_digest": action_type_digest,
            "reviewed_replay_digest": reviewed_replay_digest,
            "source_revision": source_revision,
            "scenario_set_version": scenario_set_version,
            "promotion_evidence_digest": promotion_evidence_digest,
        }
    )


__all__ = [
    "authority_text_digest",
    "canonical_authority_digest",
    "development_promotion_target_digest",
    "normalized_principal",
]
