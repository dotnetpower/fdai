"""Validation of remediation results returned from a coding-agent session.

A result file is a set of claims made on a developer machine. Import binds it to the exact pack
FDAI exported (pack id, manifest digest, base commit, issue membership, expiry, revocation) and
normalizes every status into a claim. Import never marks an issue fixed: ``fixed_verified`` needs
a coverage-equivalent rescan of the claimed commit, and false-positive or risk-acceptance claims
need FDAI's adjudication workflow.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

MAX_RESULT_BYTES = 1_000_000
_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_ISSUE = re.compile(r"^FDAI-SEC-[0-9a-f]{12}$")


class ClaimStatus(StrEnum):
    FIXED_CLAIMED = "fixed_claimed"
    MITIGATED_CLAIMED = "mitigated_claimed"
    CLAIMED_FALSE_POSITIVE = "claimed_false_positive"
    STALE_OR_ALREADY_FIXED = "stale_or_already_fixed"
    DEFERRED = "deferred"
    FAILED = "failed"
    PLAN_ONLY = "plan_only"
    NOT_ATTEMPTED = "not_attempted"


class ValidationState(StrEnum):
    TESTS_PASSED = "tests_passed"
    TESTS_FAILED = "tests_failed"
    MANUAL_VALIDATION_REQUIRED = "manual_validation_required"
    NOT_RUN = "not_run"


class NextStep(StrEnum):
    RESCAN_REQUIRED = "rescan_required"
    ADJUDICATION_REQUIRED = "adjudication_required"
    NONE = "none"


class RemediationResultRejectedError(ValueError):
    """Raised when a result cannot be bound to a known, valid pack. ``reason`` is stable."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class PackRecord:
    """FDAI's own record of an exported pack. Never reconstructed from the result file."""

    pack_id: str
    manifest_sha256: str
    base_commit: str
    issue_ids: frozenset[str]
    expires_at: datetime
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class IssueClaim:
    issue_id: str
    status: ClaimStatus
    validation: ValidationState
    commits: tuple[str, ...]
    next_step: NextStep
    evidence: str


@dataclass(frozen=True, slots=True)
class ImportedRemediationResult:
    pack_id: str
    final_head: str
    claims: tuple[IssueClaim, ...]


_NEXT_STEP = {
    ClaimStatus.FIXED_CLAIMED: NextStep.RESCAN_REQUIRED,
    ClaimStatus.MITIGATED_CLAIMED: NextStep.RESCAN_REQUIRED,
    ClaimStatus.STALE_OR_ALREADY_FIXED: NextStep.RESCAN_REQUIRED,
    ClaimStatus.CLAIMED_FALSE_POSITIVE: NextStep.ADJUDICATION_REQUIRED,
}


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]", "", value)
    return cleaned[:limit]


def import_remediation_result(
    raw: bytes, record: PackRecord, now: datetime
) -> ImportedRemediationResult:
    """Validate ``raw`` against ``record`` and return normalized claims.

    Raises :class:`RemediationResultRejectedError` for oversize or malformed input, an unknown,
    revoked, expired, or digest-mismatched pack, a different base commit, an issue outside the
    pack, an unknown status, or an invalid commit id.
    """
    if len(raw) > MAX_RESULT_BYTES:
        raise RemediationResultRejectedError("result_too_large")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemediationResultRejectedError("malformed_result", type(exc).__name__) from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise RemediationResultRejectedError("unsupported_schema")
    if document.get("pack_id") != record.pack_id:
        raise RemediationResultRejectedError("unknown_pack")
    if record.revoked:
        raise RemediationResultRejectedError("pack_revoked")
    if now > record.expires_at:
        raise RemediationResultRejectedError("pack_expired", record.expires_at.isoformat())
    if document.get("manifest_sha256") != record.manifest_sha256:
        raise RemediationResultRejectedError("manifest_digest_mismatch")
    if document.get("base_commit") != record.base_commit:
        raise RemediationResultRejectedError("base_commit_mismatch")
    final_head = document.get("final_head")
    if not isinstance(final_head, str) or _SHA.fullmatch(final_head) is None:
        raise RemediationResultRejectedError("invalid_final_head")
    items = document.get("issues")
    if not isinstance(items, list) or len(items) > len(record.issue_ids):
        raise RemediationResultRejectedError("invalid_issue_list")
    claims: list[IssueClaim] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise RemediationResultRejectedError("invalid_issue_entry")
        issue_id = item.get("issue_id")
        if not isinstance(issue_id, str) or _ISSUE.fullmatch(issue_id) is None:
            raise RemediationResultRejectedError("invalid_issue_id")
        if issue_id not in record.issue_ids:
            raise RemediationResultRejectedError("issue_not_in_pack", issue_id)
        if issue_id in seen:
            raise RemediationResultRejectedError("duplicate_issue", issue_id)
        seen.add(issue_id)
        try:
            status = ClaimStatus(str(item.get("status")))
            validation = ValidationState(str(item.get("validation", "not_run")))
        except ValueError as exc:
            raise RemediationResultRejectedError("invalid_status", issue_id) from exc
        commits = item.get("commits", [])
        if (
            not isinstance(commits, list)
            or len(commits) > 50
            or not all(isinstance(sha, str) and _SHA.fullmatch(sha) for sha in commits)
        ):
            raise RemediationResultRejectedError("invalid_commit", issue_id)
        if status in (ClaimStatus.FIXED_CLAIMED, ClaimStatus.MITIGATED_CLAIMED) and not commits:
            raise RemediationResultRejectedError("claim_without_commit", issue_id)
        claims.append(
            IssueClaim(
                issue_id=issue_id,
                status=status,
                validation=validation,
                commits=tuple(commits),
                next_step=_NEXT_STEP.get(status, NextStep.NONE),
                evidence=_text(item.get("evidence"), 2_000),
            )
        )
    return ImportedRemediationResult(record.pack_id, final_head, tuple(claims))


__all__ = [
    "MAX_RESULT_BYTES",
    "ClaimStatus",
    "ImportedRemediationResult",
    "IssueClaim",
    "NextStep",
    "PackRecord",
    "RemediationResultRejectedError",
    "ValidationState",
    "import_remediation_result",
]
