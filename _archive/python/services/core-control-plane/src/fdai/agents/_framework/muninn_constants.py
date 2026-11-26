"""Shared constants for Muninn member and framework mixins."""

from __future__ import annotations

from datetime import timedelta

_MAX_OPERATING_PATTERN_CASES = 100

_MAX_CONVERSATION_PROJECTIONS = 50_000

_CONVERSATION_PROJECTION_RECOVERY_PAGE = 128

_PUBLICATION_OUTBOX_RETAIN = 5_000

# Compaction runs every N published rows (and on maintenance) so a publish costs O(1) amortized.
_PUBLICATION_COMPACTION_INTERVAL = 64

_PUBLICATION_CAS_ATTEMPTS = 8

_PUBLICATION_CLAIM_LEASE = timedelta(minutes=5)

_PUBLICATION_MAINTENANCE_PAGE = 16

_PROJECTION_PREFIX = "pantheon/muninn/conversation-projections"

_OPERATIONAL_OUTBOX_PREFIX = "pantheon/muninn/operational-outbox"

_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0

_MAX_CONTEXT_FETCH_SAMPLES = 512

_MAX_CONTEXT_UNAVAILABLE_FACTS = 128

_PROTECTED_CONVERSATION_BUCKETS = frozenset(
    {"conversation_turns", "conversations", "user_preferences"}
)
