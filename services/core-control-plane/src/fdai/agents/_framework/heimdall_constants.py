"""Shared constants for Heimdall member and framework mixins."""

from __future__ import annotations

from datetime import timedelta

_INCIDENT_CORRELATION_DISABLED = frozenset({"none", "disabled"})

_SEVERITY_RANK = {
    severity: rank for rank, severity in enumerate(("critical", "high", "medium", "low", "info"))
}

_DETECTION_READINESS_EVENT = "detection.readiness.observed"

_STATE_KEY = "pantheon/heimdall/sensing-state"

_EPISODE_PREFIX = "pantheon/heimdall/sensing-state/episodes/"

_READINESS_PREFIX = "pantheon/heimdall/sensing-state/readiness/"

_PENDING_READINESS_PREFIX = "pantheon/heimdall/sensing-state/readiness-pending/"

_PUBLICATION_PREFIX = "pantheon/heimdall/publications/"

_PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES = 8192

_PUBLICATION_CLAIM_LEASE = timedelta(minutes=5)

_PUBLICATION_CAS_ATTEMPTS = 8

_PUBLICATION_RECOVERY_LIMIT = 5_000

_PUBLICATION_MAINTENANCE_PAGE = 16

_RULE_VALIDATION_TIMEOUT_SECONDS = 5.0

_FULL_SNAPSHOT_LIMIT = 128

_MAX_KPI_SAMPLES = 512
