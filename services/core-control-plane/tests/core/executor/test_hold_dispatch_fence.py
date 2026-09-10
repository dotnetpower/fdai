"""Focused deterministic tests for hold dispatch fencing (#640)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.executor.hold_dispatch_fence import (
    HoldFenceAuditResult,
    HoldFenceRejectionReason,
    HoldFenceState,
    HoldLineage,
    recheck_hold_fence,
    recheck_hold_fence_isolated,
)

_NOW = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
_TARGET_DIGEST = "sha256:" + "a" * 64
_RECEIPT_DIGEST = "sha256:" + "b" * 64
_LOCK_TOKEN = "lock-token-abc123"


def _make_lineage(
    *,
    release_receipt_digest: str = _RECEIPT_DIGEST,
    released_hold_revision: int = 1,
    fencing_generation: int = 2,
) -> HoldLineage:
    return HoldLineage.create(
        release_receipt_digest=release_receipt_digest,
        released_hold_revision=released_hold_revision,
        fencing_generation=fencing_generation,
    )


def _released_hold_record(
    *,
    receipt_digest: str = _RECEIPT_DIGEST,
    revision: int = 2,
    fencing_generation: int = 2,
) -> dict[str, object]:
    return {
        "state": "released",
        "revision": revision,
        "fencing_generation": fencing_generation,
        "release_receipt": {"receipt_digest": receipt_digest},
    }


class TestHoldLineage:
    def test_create(self) -> None:
        lineage = _make_lineage()
        assert lineage.execution_authority is False
        assert lineage.lineage_digest.startswith("sha256:")

    def test_deterministic(self) -> None:
        a = _make_lineage()
        b = _make_lineage()
        assert a.lineage_digest == b.lineage_digest

    def test_reject_execution_authority(self) -> None:
        lineage = _make_lineage()
        with pytest.raises(ValueError, match="execution authority"):
            HoldLineage(
                release_receipt_digest=lineage.release_receipt_digest,
                released_hold_revision=lineage.released_hold_revision,
                fencing_generation=lineage.fencing_generation,
                lineage_digest=lineage.lineage_digest,
                execution_authority=True,  # type: ignore[arg-type]
            )

    def test_reject_bad_digest(self) -> None:
        with pytest.raises(ValueError, match="release_receipt_digest"):
            HoldLineage.create(
                release_receipt_digest="bad",
                released_hold_revision=1,
                fencing_generation=2,
            )

    def test_reject_zero_revision(self) -> None:
        with pytest.raises(ValueError, match="released_hold_revision"):
            HoldLineage.create(
                release_receipt_digest=_RECEIPT_DIGEST,
                released_hold_revision=0,
                fencing_generation=2,
            )

    def test_reject_zero_generation(self) -> None:
        with pytest.raises(ValueError, match="fencing_generation"):
            HoldLineage.create(
                release_receipt_digest=_RECEIPT_DIGEST,
                released_hold_revision=1,
                fencing_generation=0,
            )


class TestRecheckHoldFence:
    def test_no_hold_no_lineage_eligible(self) -> None:
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=None,
            expected_lineage=None,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is True
        assert result.hold_state == HoldFenceState.NO_HOLD
        assert result.rejection_reasons == ()

    def test_active_hold_denied(self) -> None:
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record={"state": "active", "revision": 1},
            expected_lineage=None,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.ACTIVE_HOLD in result.rejection_reasons

    def test_malformed_hold_denied(self) -> None:
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record={"state": 42},
            expected_lineage=None,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.MALFORMED_HOLD in result.rejection_reasons

    def test_unreadable_hold_denied(self) -> None:
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record="not-a-dict",
            expected_lineage=None,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.UNREADABLE_STATE in result.rejection_reasons

    def test_released_hold_with_matching_lineage(self) -> None:
        lineage = _make_lineage()
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=_released_hold_record(),
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is True
        assert result.rejection_reasons == ()

    def test_released_hold_receipt_mismatch(self) -> None:
        lineage = _make_lineage()
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=_released_hold_record(receipt_digest="sha256:" + "9" * 64),
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.RELEASE_RECEIPT_MISMATCH in result.rejection_reasons

    def test_released_hold_generation_mismatch(self) -> None:
        lineage = _make_lineage()
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=_released_hold_record(fencing_generation=5),
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.FENCING_GENERATION_MISMATCH in result.rejection_reasons

    def test_hold_reissued_after_release(self) -> None:
        lineage = _make_lineage(fencing_generation=2)
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=_released_hold_record(revision=5, fencing_generation=2),
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.HOLD_REISSUED_AFTER_RELEASE in result.rejection_reasons

    def test_lock_ownership_unproven(self) -> None:
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=None,
            expected_lineage=None,
            lock_ownership_token=None,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.LOCK_OWNERSHIP_UNPROVEN in result.rejection_reasons

    def test_lock_ownership_empty_string(self) -> None:
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=None,
            expected_lineage=None,
            lock_ownership_token="",
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.LOCK_OWNERSHIP_UNPROVEN in result.rejection_reasons

    def test_no_hold_with_lineage_denied(self) -> None:
        """A target with declared hold lineage requires a release receipt."""
        lineage = _make_lineage()
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=None,
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.RELEASE_RECEIPT_MISSING in result.rejection_reasons

    def test_missing_release_receipt_in_record(self) -> None:
        lineage = _make_lineage()
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record={"state": "released", "revision": 2, "fencing_generation": 2},
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.RELEASE_RECEIPT_MISSING in result.rejection_reasons


class TestRecheckHoldFenceIsolated:
    """Isolated-Executor equivalent produces the same results."""

    def test_same_result_as_core(self) -> None:
        lineage = _make_lineage()
        core = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=_released_hold_record(),
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        isolated = recheck_hold_fence_isolated(
            target_digest=_TARGET_DIGEST,
            hold_record=_released_hold_record(),
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert core.eligible == isolated.eligible
        assert core.hold_state == isolated.hold_state
        assert core.rejection_reasons == isolated.rejection_reasons

    def test_active_hold_denied_isolated(self) -> None:
        result = recheck_hold_fence_isolated(
            target_digest=_TARGET_DIGEST,
            hold_record={"state": "active", "revision": 1},
            expected_lineage=None,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.ACTIVE_HOLD in result.rejection_reasons


class TestHoldFenceAuditResult:
    def test_create_from_denied(self) -> None:
        check = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record={"state": "active", "revision": 1},
            expected_lineage=None,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        audit = HoldFenceAuditResult.create(
            check_result=check,
            recorded_at=_NOW,
        )
        assert audit.audit_digest.startswith("sha256:")
        assert HoldFenceRejectionReason.ACTIVE_HOLD in audit.rejection_reasons

    def test_reject_from_eligible(self) -> None:
        check = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=None,
            expected_lineage=None,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        with pytest.raises(ValueError, match="eligible"):
            HoldFenceAuditResult.create(
                check_result=check,
                recorded_at=_NOW,
            )


class TestNewHoldBetweenReleaseAndDispatch:
    """Verify new hold appearing between release and dispatch is fenced."""

    def test_new_active_hold_blocks_dispatch(self) -> None:
        """After release, a new active hold before dispatch blocks."""
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record={"state": "active", "revision": 3},
            expected_lineage=_make_lineage(fencing_generation=2),
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.ACTIVE_HOLD in result.rejection_reasons

    def test_unknown_hold_state_blocks_dispatch(self) -> None:
        result = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record={"state": "unknown_state"},
            expected_lineage=_make_lineage(),
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert result.eligible is False
        assert HoldFenceRejectionReason.MALFORMED_HOLD in result.rejection_reasons


class TestRestart:
    """Restart/replay produces the same fence decision."""

    def test_replay_produces_same_result(self) -> None:
        lineage = _make_lineage()
        record = _released_hold_record()
        first = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=record,
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        second = recheck_hold_fence(
            target_digest=_TARGET_DIGEST,
            hold_record=record,
            expected_lineage=lineage,
            lock_ownership_token=_LOCK_TOKEN,
            checked_at=_NOW,
        )
        assert first.eligible == second.eligible
        assert first.result_digest == second.result_digest
