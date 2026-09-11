"""Fence forward dispatch against automation-hold reissue (#640).

Serialize automation-hold issue, release, and final forward dispatch on
the same logical-target fence so a new or unreadable hold cannot appear
between the last check and provider invocation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


# ---------------------------------------------------------------------------
# Hold state classification
# ---------------------------------------------------------------------------


class HoldFenceState(StrEnum):
    """Observable hold condition inside the logical-target lock."""

    NO_HOLD = "no_hold"
    ACTIVE_HOLD = "active_hold"
    RELEASED_HOLD = "released_hold"
    MALFORMED_HOLD = "malformed_hold"
    UNREADABLE = "unreadable"


class HoldFenceRejectionReason(StrEnum):
    """Why dispatch is denied by the hold fence."""

    ACTIVE_HOLD = "active_hold"
    MALFORMED_HOLD = "malformed_hold"
    UNREADABLE_STATE = "unreadable_state"
    RELEASE_RECEIPT_MISSING = "release_receipt_missing"
    RELEASE_RECEIPT_MISMATCH = "release_receipt_mismatch"
    RELEASED_REVISION_MISMATCH = "released_revision_mismatch"
    FENCING_GENERATION_MISMATCH = "fencing_generation_mismatch"
    LOCK_OWNERSHIP_UNPROVEN = "lock_ownership_unproven"
    HOLD_REISSUED_AFTER_RELEASE = "hold_reissued_after_release"
    HOLD_AUTHORIZATION_MISMATCH = "hold_authorization_mismatch"
    RECHECK_FAILED = "recheck_failed"


# ---------------------------------------------------------------------------
# Hold lineage
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HoldLineage:
    """Content-addressed release receipt binding for a previously held target."""

    release_receipt_digest: str
    released_hold_revision: int
    fencing_generation: int
    lineage_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("hold lineage MUST NOT grant execution authority")
        if _DIGEST.fullmatch(self.release_receipt_digest) is None:
            raise ValueError("hold lineage requires a valid release_receipt_digest")
        if not isinstance(self.released_hold_revision, int) or self.released_hold_revision < 1:
            raise ValueError("hold lineage released_hold_revision MUST be positive")
        if not isinstance(self.fencing_generation, int) or self.fencing_generation < 1:
            raise ValueError("hold lineage fencing_generation MUST be positive")
        expected = content_digest(
            {
                "release_receipt_digest": self.release_receipt_digest,
                "released_hold_revision": self.released_hold_revision,
                "fencing_generation": self.fencing_generation,
                "execution_authority": False,
                "lineage_digest": None,
            }
        )
        if self.lineage_digest != expected:
            raise ValueError("hold lineage digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        release_receipt_digest: str,
        released_hold_revision: int,
        fencing_generation: int,
    ) -> HoldLineage:
        digest = content_digest(
            {
                "release_receipt_digest": release_receipt_digest,
                "released_hold_revision": released_hold_revision,
                "fencing_generation": fencing_generation,
                "execution_authority": False,
                "lineage_digest": None,
            }
        )
        return cls(
            release_receipt_digest=release_receipt_digest,
            released_hold_revision=released_hold_revision,
            fencing_generation=fencing_generation,
            lineage_digest=digest,
        )


# ---------------------------------------------------------------------------
# Hold fence recheck
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HoldFenceCheckResult:
    """Immutable outcome of one hold fence recheck inside the target lock."""

    target_digest: str
    hold_state: HoldFenceState
    hold_lineage: HoldLineage | None
    eligible: bool
    rejection_reasons: tuple[HoldFenceRejectionReason, ...]
    checked_at: datetime
    lock_ownership_token: str | None
    result_digest: str

    def __post_init__(self) -> None:
        if self.eligible and self.rejection_reasons:
            raise ValueError("eligible recheck MUST NOT have rejection reasons")
        if not self.eligible and not self.rejection_reasons:
            raise ValueError("ineligible recheck MUST have rejection reasons")
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("hold fence recheck requires timezone-aware checked_at")


def recheck_hold_fence(
    *,
    target_digest: str,
    hold_record: object,
    expected_lineage: HoldLineage | None,
    lock_ownership_token: str | None,
    checked_at: datetime,
    authorized_hold_revision: int | None = None,
) -> HoldFenceCheckResult:
    """Recheck hold state inside the acquired logical-target lock.

    This runs inside each execution path's existing critical section,
    immediately before side-effect dispatch.

    ``authorized_hold_revision`` names the one active hold revision this exact
    step was separately authorized to act under, which is how an approved
    recovery step dispatches against its own held target. Any other hold state,
    including a later revision or a release, denies that authorization.
    """

    reasons: list[HoldFenceRejectionReason] = []
    hold_state = _classify_hold(hold_record)

    # Lock ownership is required for dispatch eligibility
    if not lock_ownership_token:
        reasons.append(HoldFenceRejectionReason.LOCK_OWNERSHIP_UNPROVEN)

    if authorized_hold_revision is not None:
        if expected_lineage is not None:
            reasons.append(HoldFenceRejectionReason.HOLD_AUTHORIZATION_MISMATCH)
        if hold_state is not HoldFenceState.ACTIVE_HOLD or not _matches_authorized_revision(
            hold_record,
            authorized_hold_revision,
        ):
            reasons.append(HoldFenceRejectionReason.HOLD_AUTHORIZATION_MISMATCH)
            if hold_state is HoldFenceState.ACTIVE_HOLD:
                reasons.append(HoldFenceRejectionReason.ACTIVE_HOLD)
            elif hold_state is HoldFenceState.MALFORMED_HOLD:
                reasons.append(HoldFenceRejectionReason.MALFORMED_HOLD)
            elif hold_state is HoldFenceState.UNREADABLE:
                reasons.append(HoldFenceRejectionReason.UNREADABLE_STATE)
        return _result(
            target_digest=target_digest,
            hold_state=hold_state,
            expected_lineage=expected_lineage,
            reasons=reasons,
            lock_ownership_token=lock_ownership_token,
            checked_at=checked_at,
        )

    if hold_state == HoldFenceState.ACTIVE_HOLD:
        reasons.append(HoldFenceRejectionReason.ACTIVE_HOLD)
    elif hold_state == HoldFenceState.MALFORMED_HOLD:
        reasons.append(HoldFenceRejectionReason.MALFORMED_HOLD)
    elif hold_state == HoldFenceState.UNREADABLE:
        reasons.append(HoldFenceRejectionReason.UNREADABLE_STATE)
    elif hold_state == HoldFenceState.RELEASED_HOLD:
        # Verify release receipt matches expected lineage
        if expected_lineage is not None:
            _check_released_lineage(hold_record, expected_lineage, reasons)
        # Check for reissue after release
        if isinstance(hold_record, dict):
            revision = hold_record.get("revision")
            if expected_lineage is not None and isinstance(revision, int):
                if revision > expected_lineage.fencing_generation:
                    reasons.append(HoldFenceRejectionReason.HOLD_REISSUED_AFTER_RELEASE)
    elif hold_state == HoldFenceState.NO_HOLD:
        # No hold: only valid when no declared hold lineage
        if expected_lineage is not None:
            reasons.append(HoldFenceRejectionReason.RELEASE_RECEIPT_MISSING)

    return _result(
        target_digest=target_digest,
        hold_state=hold_state,
        expected_lineage=expected_lineage,
        reasons=reasons,
        lock_ownership_token=lock_ownership_token,
        checked_at=checked_at,
    )


def _result(
    *,
    target_digest: str,
    hold_state: HoldFenceState,
    expected_lineage: HoldLineage | None,
    reasons: list[HoldFenceRejectionReason],
    lock_ownership_token: str | None,
    checked_at: datetime,
) -> HoldFenceCheckResult:
    eligible = len(reasons) == 0
    result_digest = content_digest(
        {
            "target_digest": target_digest,
            "hold_state": hold_state.value,
            "eligible": eligible,
            "rejection_reasons": [r.value for r in sorted(set(reasons), key=str)],
            "checked_at": checked_at.astimezone(UTC).isoformat(),
        }
    )

    return HoldFenceCheckResult(
        target_digest=target_digest,
        hold_state=hold_state,
        hold_lineage=expected_lineage,
        eligible=eligible,
        rejection_reasons=tuple(sorted(set(reasons), key=str)),
        checked_at=checked_at,
        lock_ownership_token=lock_ownership_token,
        result_digest=result_digest,
    )


def _matches_authorized_revision(hold_record: object, authorized_hold_revision: int) -> bool:
    if not isinstance(hold_record, dict):
        return False
    revision = hold_record.get("revision")
    return (
        isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision == authorized_hold_revision
    )


def recheck_hold_fence_isolated(
    *,
    target_digest: str,
    hold_record: object,
    expected_lineage: HoldLineage | None,
    lock_ownership_token: str | None,
    checked_at: datetime,
    authorized_hold_revision: int | None = None,
) -> HoldFenceCheckResult:
    """Isolated-Executor equivalent without importing Core implementation."""

    return recheck_hold_fence(
        target_digest=target_digest,
        hold_record=hold_record,
        expected_lineage=expected_lineage,
        lock_ownership_token=lock_ownership_token,
        checked_at=checked_at,
        authorized_hold_revision=authorized_hold_revision,
    )


# ---------------------------------------------------------------------------
# Audit result for denied dispatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HoldFenceAuditResult:
    """Bounded audit record for a fenced dispatch denial."""

    target_digest: str
    rejection_reasons: tuple[HoldFenceRejectionReason, ...]
    hold_state: HoldFenceState
    recorded_at: datetime
    audit_digest: str

    def __post_init__(self) -> None:
        if not self.rejection_reasons:
            raise ValueError("hold fence audit requires at least one rejection reason")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("hold fence audit requires timezone-aware recorded_at")

    @classmethod
    def create(
        cls,
        *,
        check_result: HoldFenceCheckResult,
        recorded_at: datetime,
    ) -> HoldFenceAuditResult:
        if check_result.eligible:
            raise ValueError("cannot create audit result for eligible hold fence check")
        audit_digest = content_digest(
            {
                "target_digest": check_result.target_digest,
                "rejection_reasons": [r.value for r in check_result.rejection_reasons],
                "hold_state": check_result.hold_state.value,
                "recorded_at": recorded_at.astimezone(UTC).isoformat(),
            }
        )
        return cls(
            target_digest=check_result.target_digest,
            rejection_reasons=check_result.rejection_reasons,
            hold_state=check_result.hold_state,
            recorded_at=recorded_at,
            audit_digest=audit_digest,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_hold(record: object) -> HoldFenceState:
    """Classify hold state from a raw record."""

    if record is None:
        return HoldFenceState.NO_HOLD
    if not isinstance(record, dict):
        return HoldFenceState.UNREADABLE
    state = record.get("state")
    if state is None:
        return HoldFenceState.NO_HOLD
    if not isinstance(state, str):
        return HoldFenceState.MALFORMED_HOLD
    if state == "active":
        return HoldFenceState.ACTIVE_HOLD
    if state == "released":
        revision = record.get("revision")
        if not isinstance(revision, int) or revision < 1:
            return HoldFenceState.MALFORMED_HOLD
        return HoldFenceState.RELEASED_HOLD
    return HoldFenceState.MALFORMED_HOLD


def _check_released_lineage(
    hold_record: object,
    lineage: HoldLineage,
    reasons: list[HoldFenceRejectionReason],
) -> None:
    """Verify released hold matches the expected lineage."""

    if not isinstance(hold_record, dict):
        reasons.append(HoldFenceRejectionReason.RECHECK_FAILED)
        return
    release_receipt = hold_record.get("release_receipt")
    if not isinstance(release_receipt, dict):
        reasons.append(HoldFenceRejectionReason.RELEASE_RECEIPT_MISSING)
        return
    receipt_digest = release_receipt.get("receipt_digest")
    if receipt_digest != lineage.release_receipt_digest:
        reasons.append(HoldFenceRejectionReason.RELEASE_RECEIPT_MISMATCH)
    fencing_gen = hold_record.get("fencing_generation")
    if fencing_gen != lineage.fencing_generation:
        reasons.append(HoldFenceRejectionReason.FENCING_GENERATION_MISMATCH)


__all__ = [
    "HoldFenceAuditResult",
    "HoldFenceCheckResult",
    "HoldFenceRejectionReason",
    "HoldFenceState",
    "HoldLineage",
    "recheck_hold_fence",
    "recheck_hold_fence_isolated",
]
