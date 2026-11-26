"""Shared constants for Saga member and framework mixins."""

from __future__ import annotations

from datetime import timedelta

_FINGERPRINT_BUCKET = "issue_fingerprint_index"

_AUDIT_OUTBOX_PREFIX = "pantheon/saga/audit-outbox/"

_FINGERPRINT_PREFIX = "pantheon/saga/issue-fingerprint/"

_ISSUE_CLOSE_ELIGIBILITY_PREFIX = "pantheon/saga/issue-close-eligibility/"

_AUDIT_OUTBOX_PENDING_SCAN_LIMIT = 5_000

_AUDIT_OUTBOX_MAINTENANCE_PAGE = 16

# Published outbox tombstones retain only digests long enough to suppress
# duplicate redelivery across restarts while keeping prefix scans bounded.
_AUDIT_OUTBOX_TOMBSTONE_RETENTION = 1_024

_AUDIT_OUTBOX_CLAIM_LEASE = timedelta(minutes=5)

_FORECAST_AUDIT_FENCE_SIZE = 10_000

_MAX_FINGERPRINT_INDEX = 50_000

_FINGERPRINT_RETENTION = 10_000

_ISSUE_CLOSE_CLEAN_WINDOW = timedelta(hours=24)

_ISSUE_CLOSE_ELIGIBILITY_BUCKET = "issue_close_eligibility"

_MAX_HANDOFF_CONTEXT_ITEMS = 8

_MAX_HANDOFF_CONTEXT_VALUE_CHARS = 256

_HANDOFF_CONTEXT_KEYS = frozenset(
    {
        "context_ref",
        "evidence_ref",
        "handoff_ref",
        "payload_digest",
        "source_ref",
        "trace_ref",
    }
)

_NON_LEARNABLE_TERMINAL_STATES = frozenset(
    {"deny_dropped", "rejected", "expired", "approval_expired"}
)
