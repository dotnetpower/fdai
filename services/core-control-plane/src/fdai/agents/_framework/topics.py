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

from collections.abc import Mapping
from typing import Any

# Envelope schema version stamped on every published record. Bumped only
# on a breaking change to the shared envelope shape (correlation_id /
# idempotency_key / producer_principal semantics), so consumers can gate
# on it during a rolling upgrade.
ENVELOPE_SCHEMA_VERSION = 1

# Topics whose payloads mutate a resource - partition by `resource_id`
# so concurrent writes to the same resource serialize. Public so the bus
# bridge shares one source of truth (no second copy that can drift).
MUTATION_TOPICS: frozenset[str] = frozenset(
    {
        "object.action-run",
        "object.action-attempt",
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
        # Judgment + arbitration
        "object.verdict",
        "object.rca",
        "object.arbitration-request",
        "object.arbitration-decision",
        # Execution + recovery
        "object.action-run",
        "object.action-attempt",
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
        "object.pattern-observation",
        "object.state-snapshot",
        "object.context-index",
        "object.rule-generation-build-request",
        "object.rule-generation-build-result",
        # Security
        "object.security-event",
        # Domain
        "object.cost-anomaly",
        "object.budget",
        "object.capacity-forecast",
        "object.sizing-recommendation",
        "object.chaos-experiment",
        "object.resilience-score",
    }
)


def topic_for_object_type(object_type: str) -> str:
    """Camel-case ObjectType name -> `object.<kebab>` topic form."""
    return f"object.{_kebab(object_type)}"


def partition_key_for(topic: str, payload: dict[str, Any]) -> str:
    """Return the partition key for a given topic + payload.

    Falls back to `correlation_id` when the payload lacks a
    resource-scoped identifier on a mutation topic (bus adapter should
    log this as a data-quality signal for Norns).
    """
    if topic in _MUTATION_TOPICS:
        return str(payload.get("resource_id") or payload.get("correlation_id", ""))
    if topic in _CORRELATION_TOPICS:
        return str(payload.get("correlation_id", ""))
    # Default: correlation_id if present, else empty (random partition).
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
    "missing_mutation_envelope_fields",
    "topic_for_object_type",
    "partition_key_for",
]
