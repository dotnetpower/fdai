"""Ownership-through-commit policy and terminal evidence tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.core.executor.lock_continuity import (
    DispatchState,
    EffectSinkContinuityPolicy,
    IndependentEffectState,
    LockReleaseState,
    OwnershipContinuityReceipt,
    OwnershipContinuityStrategy,
    SinkCommitState,
    _normalize_digest_value,
)
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
)

_NOW = datetime(2026, 9, 10, 7, 0, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64


def _policy(
    strategy: OwnershipContinuityStrategy = OwnershipContinuityStrategy.FENCED_IDEMPOTENT,
) -> EffectSinkContinuityPolicy:
    if strategy is OwnershipContinuityStrategy.FENCED_IDEMPOTENT:
        return EffectSinkContinuityPolicy.create(
            sink_id="example-sink",
            sink_version="1.0.0",
            strategy=strategy,
            sink_fencing=True,
            stable_sink_idempotency=True,
        )
    if strategy is OwnershipContinuityStrategy.LOCK_SESSION_ATOMIC:
        return EffectSinkContinuityPolicy.create(
            sink_id="example-sink",
            sink_version="1.0.0",
            strategy=strategy,
            same_session_effect_commit=True,
            same_session_reservation_terminalization=True,
            same_session_outbox_publication=True,
        )
    return EffectSinkContinuityPolicy.create(
        sink_id="example-sink",
        sink_version="1.0.0",
        strategy=strategy,
        cancellation_supported=True,
        durable_unknown_quarantine=True,
        reconciliation_supported=True,
    )


def _lock_evidence(
    *,
    session: bool = False,
) -> tuple[
    ResourceLockAcquisitionReceipt,
    LiveLockOwnershipAssessment,
]:
    request = ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest="sha256:" + "1" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "b" * 40,
    )
    receipt = ResourceLockAcquisitionReceipt.create(
        lock_key=request.lock_key,
        target_digest=request.target_digest,
        action_digest=request.action_digest,
        attempt=request.attempt,
        provider_id="postgres-advisory-lock",
        provider_version="1.0.0",
        producer_id=request.producer_id,
        producer_version=request.producer_version,
        owner_token_digest="sha256:" + "2" * 64,
        fencing_generation=None if session else 7,
        session_identity="session:example" if session else None,
        provider_attestation_digest="sha256:" + "3" * 64,
        trust_anchor_id="postgres:primary",
        acquired_at=_NOW,
        valid_until=None if session else _NOW + timedelta(seconds=5),
        source_revision=request.source_revision,
        request_digest=request.request_digest,
    )
    assessment = LiveLockOwnershipAssessment.create(
        receipt,
        current_fencing_generation=None if session else 7,
        current_session_identity="session:example" if session else None,
        verifier_id="postgres-lock-readback",
        verifier_version="1.0.0",
        trust_anchor_id=receipt.trust_anchor_id,
        provider_attestation_digest="sha256:" + "4" * 64,
        evaluated_at=_NOW,
        valid_until=_NOW + timedelta(seconds=1),
    )
    return receipt, assessment


def _continuity(
    *,
    policy: EffectSinkContinuityPolicy | None = None,
    session: bool = False,
    dispatch_state: DispatchState = DispatchState.ACCEPTED,
    sink_commit_state: SinkCommitState = SinkCommitState.COMMITTED,
    independent_effect_state: IndependentEffectState = IndependentEffectState.PENDING,
    release_state: LockReleaseState = LockReleaseState.RELEASED,
    authoritative_status_digest: str | None = None,
    independent_effect_receipt_digest: str | None = None,
) -> OwnershipContinuityReceipt:
    acquisition, assessment = _lock_evidence(session=session)
    return OwnershipContinuityReceipt.create(
        policy=policy or _policy(),
        acquisition_receipt=acquisition,
        final_ownership_assessment=assessment,
        dispatch_state=dispatch_state,
        sink_commit_state=sink_commit_state,
        independent_effect_state=independent_effect_state,
        release_state=release_state,
        authoritative_status_digest=authoritative_status_digest,
        independent_effect_receipt_digest=independent_effect_receipt_digest,
        ownership_observed_at=_NOW,
        recorded_at=_NOW + timedelta(microseconds=1),
    )


@pytest.mark.parametrize("strategy", list(OwnershipContinuityStrategy))
def test_reviewed_continuity_strategies_are_no_authority(
    strategy: OwnershipContinuityStrategy,
) -> None:
    policy = _policy(strategy)
    assert policy.execution_authority is False
    assert policy.effect_verification_authority is False


@pytest.mark.parametrize(
    ("strategy", "kwargs"),
    [
        (OwnershipContinuityStrategy.FENCED_IDEMPOTENT, {"sink_fencing": True}),
        (
            OwnershipContinuityStrategy.LOCK_SESSION_ATOMIC,
            {"same_session_effect_commit": True},
        ),
        (
            OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION,
            {"cancellation_supported": True},
        ),
    ],
)
def test_incomplete_continuity_strategy_fails_closed(
    strategy: OwnershipContinuityStrategy,
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        EffectSinkContinuityPolicy.create(
            sink_id="example-sink",
            sink_version="1.0.0",
            strategy=strategy,
            **kwargs,  # type: ignore[arg-type]
        )


def test_committed_sink_remains_distinct_from_independent_effect_success() -> None:
    continuity = _continuity()
    verified = _continuity(
        independent_effect_state=IndependentEffectState.VERIFIED,
        independent_effect_receipt_digest=_DIGEST,
    )

    assert continuity.sink_commit_state is SinkCommitState.COMMITTED
    assert continuity.independent_effect_state is IndependentEffectState.PENDING
    assert continuity.effect_verified is False
    assert verified.independent_effect_state is IndependentEffectState.VERIFIED
    assert verified.effect_verified is False
    assert verified.receipt_digest != continuity.receipt_digest


@pytest.mark.parametrize(
    ("dispatch", "commit", "release"),
    [
        (DispatchState.NOT_STARTED, SinkCommitState.NOT_STARTED, LockReleaseState.LOST),
        (DispatchState.ACCEPTED, SinkCommitState.UNKNOWN, LockReleaseState.LOST),
        (DispatchState.ACCEPTED, SinkCommitState.COMMITTED, LockReleaseState.UNKNOWN),
    ],
)
def test_loss_unknown_and_commit_before_record_require_quarantine(
    dispatch: DispatchState,
    commit: SinkCommitState,
    release: LockReleaseState,
) -> None:
    continuity = _continuity(
        dispatch_state=dispatch,
        sink_commit_state=commit,
        release_state=release,
    )
    assert continuity.quarantine_required is True


def test_authoritative_non_acceptance_can_clear_unknown_quarantine() -> None:
    unknown = _continuity(
        dispatch_state=DispatchState.ACCEPTED,
        sink_commit_state=SinkCommitState.UNKNOWN,
        release_state=LockReleaseState.UNKNOWN,
    )
    reconciled = _continuity(
        dispatch_state=DispatchState.NOT_ACCEPTED,
        sink_commit_state=SinkCommitState.NOT_COMMITTED,
        release_state=LockReleaseState.RELEASED,
        authoritative_status_digest=_DIGEST,
    )

    assert unknown.quarantine_required is True
    assert reconciled.quarantine_required is False


@pytest.mark.parametrize(
    "dispatch_state",
    [DispatchState.ATTEMPTED, DispatchState.ACCEPTED],
)
def test_non_commit_does_not_clear_ambiguous_dispatch_quarantine(
    dispatch_state: DispatchState,
) -> None:
    continuity = _continuity(
        dispatch_state=dispatch_state,
        sink_commit_state=SinkCommitState.NOT_COMMITTED,
        release_state=LockReleaseState.RELEASED,
        authoritative_status_digest=_DIGEST,
    )
    assert continuity.quarantine_required is True


def test_stale_final_ownership_and_tampering_fail_closed() -> None:
    acquisition, assessment = _lock_evidence()
    with pytest.raises(ValueError, match="stale"):
        OwnershipContinuityReceipt.create(
            policy=_policy(),
            acquisition_receipt=acquisition,
            final_ownership_assessment=assessment,
            dispatch_state=DispatchState.ACCEPTED,
            sink_commit_state=SinkCommitState.UNKNOWN,
            independent_effect_state=IndependentEffectState.PENDING,
            release_state=LockReleaseState.UNKNOWN,
            authoritative_status_digest=None,
            independent_effect_receipt_digest=None,
            ownership_observed_at=assessment.valid_until,
            recorded_at=assessment.valid_until,
        )
    with pytest.raises(ValueError, match="digest mismatched"):
        replace(_continuity(), receipt_digest="sha256:" + "0" * 64)


def test_invalid_terminal_axis_combinations_fail_closed() -> None:
    with pytest.raises(ValueError, match="undispatched"):
        _continuity(
            dispatch_state=DispatchState.NOT_STARTED,
            sink_commit_state=SinkCommitState.COMMITTED,
        )
    with pytest.raises(ValueError, match="requires its receipt"):
        _continuity(independent_effect_state=IndependentEffectState.VERIFIED)
    with pytest.raises(ValueError, match="authoritative"):
        _continuity(
            dispatch_state=DispatchState.NOT_ACCEPTED,
            sink_commit_state=SinkCommitState.NOT_COMMITTED,
        )


def test_continuity_strategy_requires_matching_acquisition_lifetime() -> None:
    with pytest.raises(ValueError, match="session acquisition"):
        _continuity(policy=_policy(OwnershipContinuityStrategy.LOCK_SESSION_ATOMIC))
    with pytest.raises(ValueError, match="fenced lease"):
        _continuity(
            policy=_policy(OwnershipContinuityStrategy.FENCED_IDEMPOTENT),
            session=True,
        )


def test_continuity_receipt_is_deterministic_and_no_authority() -> None:
    first = _continuity()
    second = _continuity()
    assert first == second
    assert first.execution_authority is False
    assert first.effect_verified is False


def test_policy_validation_and_subclass_guards() -> None:
    policy = _policy()
    with pytest.raises(TypeError, match="does not support subclasses"):

        class _SubPolicy(EffectSinkContinuityPolicy):
            pass

        _SubPolicy.create(
            sink_id="example-sink",
            sink_version="1.0.0",
            strategy=OwnershipContinuityStrategy.FENCED_IDEMPOTENT,
            sink_fencing=True,
            stable_sink_idempotency=True,
        )

    with pytest.raises(ValueError, match="unsupported effect sink continuity policy schema"):
        replace(policy, schema_version="2.0.0")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(policy, execution_authority=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MUST be bounded"):
        replace(policy, sink_id="   ")
    with pytest.raises(ValueError, match="strategy is invalid"):
        replace(policy, strategy="invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="capabilities MUST be boolean"):
        replace(policy, sink_fencing="yes")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MUST be SHA-256"):
        replace(policy, policy_digest="bad-digest")
    with pytest.raises(ValueError, match="policy digest mismatched"):
        replace(policy, policy_digest="sha256:" + "0" * 64)


def test_receipt_validation_and_terminal_axis_guards() -> None:
    continuity = _continuity(
        authoritative_status_digest=_DIGEST,
        independent_effect_state=IndependentEffectState.VERIFIED,
        independent_effect_receipt_digest=_DIGEST,
    )
    acquisition, assessment = _lock_evidence()
    other_acq, _ = _lock_evidence(session=True)

    with pytest.raises(TypeError, match="does not support subclasses"):

        class _SubReceipt(OwnershipContinuityReceipt):
            pass

        _SubReceipt.create(
            policy=_policy(),
            acquisition_receipt=acquisition,
            final_ownership_assessment=assessment,
            dispatch_state=DispatchState.ACCEPTED,
            sink_commit_state=SinkCommitState.COMMITTED,
            independent_effect_state=IndependentEffectState.PENDING,
            release_state=LockReleaseState.RELEASED,
            authoritative_status_digest=None,
            independent_effect_receipt_digest=None,
            ownership_observed_at=_NOW,
            recorded_at=_NOW,
        )

    with pytest.raises(ValueError, match="unsupported ownership continuity receipt schema"):
        replace(continuity, schema_version="2.0.0")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(continuity, execution_authority=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exact sink policy"):
        replace(continuity, policy="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exact acquisition receipt"):
        replace(continuity, acquisition_receipt="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exact ownership assessment"):
        replace(continuity, final_ownership_assessment="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="does not bind the acquisition"):
        replace(continuity, acquisition_receipt=other_acq)
    with pytest.raises(ValueError, match="dispatch state is invalid"):
        replace(continuity, dispatch_state="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot follow recording"):
        replace(continuity, ownership_observed_at=_NOW + timedelta(seconds=2))
    with pytest.raises(ValueError, match="quarantine flag MUST be boolean"):
        replace(continuity, quarantine_required="no")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="quarantine flag mismatched"):
        replace(continuity, quarantine_required=True)
    with pytest.raises(ValueError, match="MUST include a timezone"):
        OwnershipContinuityReceipt.create(
            policy=_policy(),
            acquisition_receipt=acquisition,
            final_ownership_assessment=assessment,
            dispatch_state=DispatchState.ACCEPTED,
            sink_commit_state=SinkCommitState.COMMITTED,
            independent_effect_state=IndependentEffectState.PENDING,
            release_state=LockReleaseState.RELEASED,
            authoritative_status_digest=None,
            independent_effect_receipt_digest=None,
            ownership_observed_at=datetime(2026, 9, 10, 7, 0),
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="normalized to UTC"):
        replace(
            continuity,
            recorded_at=datetime(2026, 9, 10, 8, 0, tzinfo=timezone(timedelta(hours=1))),
        )
    with pytest.raises(ValueError, match="authoritative non-commit"):
        _continuity(
            dispatch_state=DispatchState.NOT_ACCEPTED,
            sink_commit_state=SinkCommitState.UNKNOWN,
            authoritative_status_digest=_DIGEST,
        )
    with pytest.raises(ValueError, match="cannot retain a not-started sink state"):
        _continuity(
            dispatch_state=DispatchState.ATTEMPTED,
            sink_commit_state=SinkCommitState.NOT_STARTED,
        )
    with pytest.raises(ValueError, match="sink commit requires accepted dispatch"):
        _continuity(
            dispatch_state=DispatchState.ATTEMPTED,
            sink_commit_state=SinkCommitState.COMMITTED,
        )
    with pytest.raises(ValueError, match="sink non-commit requires authoritative status"):
        _continuity(
            dispatch_state=DispatchState.ATTEMPTED,
            sink_commit_state=SinkCommitState.NOT_COMMITTED,
            authoritative_status_digest=None,
        )
    with pytest.raises(ValueError, match="cannot carry a decision receipt"):
        _continuity(
            independent_effect_state=IndependentEffectState.PENDING,
            independent_effect_receipt_digest=_DIGEST,
        )

    normalized = _normalize_digest_value((continuity, [_policy()]))
    assert isinstance(normalized, list)
