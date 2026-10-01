"""Shared Loki runtime constants."""

from __future__ import annotations

from datetime import timedelta

_CHAOS_EVIDENCE_FIELDS = (
    "causal_hypothesis_ref",
    "refutation_query_ref",
    "impact_envelope_id",
    "recovery_plan_id",
    "dry_run_receipt",
)
_CHAOS_OUTBOX_PREFIX = "pantheon/loki/chaos-outbox/"
_HELD_PREFIX = "pantheon/loki/held-proposals/"
_RESILIENCE_PREFIX = "pantheon/loki/resilience-scores/"
_SAFE_CLOSURE_STATES = frozenset({"succeeded", "rejected", "deny_dropped", "rolled_back"})
_MAX_HELD_PROPOSALS = 256
_MAX_RESILIENCE_SCORES = 512
_DEFAULT_RESERVATION_TTL = timedelta(minutes=30)
_MAX_CHAOS_TARGETS = 32
_MAX_CHAOS_IDENTIFIER_CHARS = 512

__all__ = [
    "_CHAOS_EVIDENCE_FIELDS",
    "_CHAOS_OUTBOX_PREFIX",
    "_DEFAULT_RESERVATION_TTL",
    "_HELD_PREFIX",
    "_MAX_CHAOS_IDENTIFIER_CHARS",
    "_MAX_CHAOS_TARGETS",
    "_MAX_HELD_PROPOSALS",
    "_MAX_RESILIENCE_SCORES",
    "_RESILIENCE_PREFIX",
    "_SAFE_CLOSURE_STATES",
]
