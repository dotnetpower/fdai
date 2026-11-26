"""Shared constants for Mimir member and framework mixins."""

from __future__ import annotations

import re
from datetime import timedelta

#: Cap on retained rejected-candidate records. Quarantine holds candidates the
#: CandidateGuard REJECTED - i.e. attacker-controlled volume under a
#: candidate-poisoning attempt. An unbounded list would be a memory-exhaustion
#: DoS vector: a poisoning flood grows it without limit. The durable audit
#: trail is Saga's chain; this in-memory list is a bounded diagnostic ring.
_MAX_QUARANTINE = 5_000

_MAX_PENDING_CANDIDATES = 5_000

_MAX_CATALOG_REVIEW_PACKAGES = 5_000

_MAX_ISSUE_FINGERPRINTS = 50_000

_GOVERNANCE_RECOVERY_PAGE = 128

_RULE_GENERATION_RECEIPT_RETAIN = 5_000

_MAX_PROMOTION_PERSIST_QUEUE = 1_024

_MAX_PROMOTION_PERSIST_ATTEMPTS = 8

_RULE_PUBLICATION_CLAIM_LEASE = timedelta(minutes=5)

_RULE_PUBLICATION_MAINTENANCE_PAGE = 16

_MAX_MAINTENANCE_RECORDS = 128

_OPERATIONAL_RULE_PREFIX = "learned.operational."

_RULE_GENERATION_RECEIPT_PREFIX = "mimir:rule-generation-activation-result:"

_RULE_GENERATION_VALIDATION_PREFIX = "mimir:rule-generation-validation-result:"

_RULE_GENERATION_COMMAND_PREFIX = "mimir:rule-generation-activation-command:"

_GOVERNANCE_PREFIX = "pantheon/mimir/governance"

_RULE_STATE_PREFIX = f"{_GOVERNANCE_PREFIX}/rules"

_ISSUE_FINGERPRINT_PREFIX = f"{_GOVERNANCE_PREFIX}/issue-fingerprints"

_RULE_PUBLICATION_PREFIX = f"{_GOVERNANCE_PREFIX}/rule-publications"

_DEPRECATION_CANDIDATE_PREFIX = f"{_GOVERNANCE_PREFIX}/deprecation-candidates"

_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0

_REVIEWED_REPOSITORY_PREFIX = re.compile(
    r"^https://(?P<host>[A-Za-z0-9.-]{1,253})/"
    r"(?P<owner>[A-Za-z0-9_.-]{1,100})/"
    r"(?P<repo>[A-Za-z0-9_.-]{1,100})$"
)

_REVIEWED_CATALOG_PR_REF = re.compile(
    r"^catalog-pr:(?P<repository>https://[A-Za-z0-9.-]{1,253}/"
    r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100})/"
    r"pull/[1-9][0-9]{0,18}@sha256:"
    r"(?P<digest>[a-f0-9]{64})$"
)

_REVIEWED_CATALOG_COMMIT_REF = re.compile(
    r"^catalog-commit:[a-f0-9]{40}@sha256:(?P<digest>[a-f0-9]{64})$"
)
