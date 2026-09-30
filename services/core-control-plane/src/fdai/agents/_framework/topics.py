"""Topic naming and partition-key strategy.

Per `agent-pantheon.md` \u00a76.1:
- Topics are `object.<kebab-type>` (e.g. `object.action-run`).
- Mutation topics partition by `resource_id` (per-resource mutex).
- Judgment / audit topics partition by `correlation_id`.
- Everything carries `correlation_id`, `idempotency_key`,
  `producer_principal`.

This module is data + pure functions; no I/O. The bus adapter wraps
these to enforce the contract before publish.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

# Envelope schema version stamped on every published record. Bumped only
# on a breaking change to the shared envelope shape (correlation_id /
# idempotency_key / producer_principal semantics), so consumers can gate
# on it during a rolling upgrade.
ENVELOPE_SCHEMA_VERSION = 1
MAX_ENVELOPE_FIELD_CHARS = 512

# Topics whose payloads mutate a resource - partition by `resource_id`
# so concurrent writes to the same resource serialize. Public so the bus
# bridge shares one source of truth (no second copy that can drift).
MUTATION_TOPICS: frozenset[str] = frozenset(
    {
        "object.action-run",
        "object.rollback",
    }
)

# Topics whose payloads carry an approval or human decision - partition
# by `correlation_id` so the whole HIL round-trip stays on one consumer.
CORRELATION_TOPICS: frozenset[str] = frozenset(
    {
        "object.verdict",
        "object.approval",
        "object.arbitration-request",
        "object.arbitration-decision",
        "object.prospective-lineage",
        "object.audit-entry",
        "object.security-event",
    }
)

# Backwards-compatible private aliases (kept so any internal reference to
# the old names keeps working; the public names above are canonical).
_MUTATION_TOPICS = MUTATION_TOPICS
_CORRELATION_TOPICS = CORRELATION_TOPICS


# All object topics recognized by the topic namespace.
# The registry uses this list to reject publishes to unknown topics.
OWNED_OBJECT_TOPICS: frozenset[str] = frozenset(
    {
        # Sensing
        "object.event",
        "object.change",
        "object.anomaly",
        "object.drift",
        "object.forecast",
        "object.forecast-outcome",
        "object.retrieval-validation",
        "object.evidence-conflict",
        "object.recovery-effect-observation",
        # Judgment + arbitration
        "object.verdict",
        "object.arbitration-request",
        "object.arbitration-decision",
        "object.prospective-lineage",
        # Execution + recovery
        "object.action-run",
        "object.rollback",
        # HIL + narrator
        "object.approval",
        "object.conversation",
        "object.turn",
        "object.user-preference",
        "object.handoff-escalation",
        "object.post-turn-review",
        # Governance
        "object.audit-entry",
        "object.issue",
        "object.rule",
        "object.policy",
        "object.rule-candidate",
        "object.pattern",
        "object.state-snapshot",
        "object.context-index",
        "object.rule-generation-build-request",
        "object.rule-generation-build-result",
        # Security
        "object.security-event",
        # Domain
        "object.cost-anomaly",
        "object.capacity-forecast",
        "object.capacity-graduation-recommendation",
        "object.chaos-experiment",
        "object.resilience-score",
    }
)


def topic_for_object_type(object_type: str) -> str:
    """Camel-case ObjectType name -> `object.<kebab>` topic form."""
    return f"object.{_kebab(object_type)}"


def partition_key_for(topic: str, payload: dict[str, Any]) -> str:
    """Return the partition key for a given topic + payload.

    Mutation topics use the resource key the bus requires. Every other
    owned topic uses the shared correlation key. The publish boundary is
    responsible for rejecting or counting missing envelope values; this
    helper only projects the already-enforced envelope into a broker key.
    """
    if topic in _MUTATION_TOPICS:
        return str(payload.get("resource_id", ""))
    return str(payload.get("correlation_id", ""))


def missing_mutation_envelope_fields(
    topic: str,
    payload: Mapping[str, object],
) -> tuple[str, ...]:
    """Return required mutation-envelope fields that are empty or absent."""
    if topic not in MUTATION_TOPICS:
        return ()
    return tuple(
        field_name
        for field_name in ("correlation_id", "resource_id", "idempotency_key")
        if not str(payload.get(field_name, "")).strip()
    )


def normalize_owned_object_envelope(
    topic: str,
    payload: dict[str, Any],
) -> tuple[str, ...]:
    """Strip and validate shared envelope keys for owned object topics."""
    if topic not in OWNED_OBJECT_TOPICS:
        return ()
    invalid: list[str] = []
    for field_name in ("correlation_id", "idempotency_key"):
        value = str(payload.get(field_name, "")).strip()
        if not value:
            invalid.append(field_name)
            continue
        if len(value) > MAX_ENVELOPE_FIELD_CHARS:
            invalid.append(field_name)
            continue
        payload[field_name] = value
    return tuple(invalid)


def stable_idempotency_key(kind: str, *parts: object) -> str:
    """Return a deterministic idempotency key for one logical publication.

    The key depends only on ``kind`` and the canonical JSON form of ``parts``,
    so a redelivered or recomputed publication receives the same key while a
    different logical publication receives a different one. Parts MUST be
    JSON-native values; an unsupported type raises instead of hashing an
    unstable ``repr``.
    """
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("idempotency key kind MUST be a non-empty string")
    normalized_kind = kind.strip()
    canonical = json.dumps(
        [normalized_kind, *parts],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{normalized_kind}:{digest[:32]}"


def _kebab(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i and not name[i - 1].isupper():
            out.append("-")
        out.append(ch.lower())
    return "".join(out)


__all__ = [
    "OWNED_OBJECT_TOPICS",
    "MUTATION_TOPICS",
    "CORRELATION_TOPICS",
    "ENVELOPE_SCHEMA_VERSION",
    "MAX_ENVELOPE_FIELD_CHARS",
    "missing_mutation_envelope_fields",
    "normalize_owned_object_envelope",
    "stable_idempotency_key",
    "topic_for_object_type",
    "partition_key_for",
]
