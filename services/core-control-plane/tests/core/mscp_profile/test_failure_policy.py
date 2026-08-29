"""Bounded MSCP failure-policy tests."""

from __future__ import annotations

import pytest
from fdai.core.mscp_profile.effect_verification import EffectVerificationReason
from fdai.core.mscp_profile.failure_policy import (
    MscpFailureDisposition,
    decide_mscp_failure,
)
from fdai.core.mscp_profile.profile_lifecycle import MscpProfileMode


def test_every_failure_reason_has_explicit_bounded_behavior() -> None:
    failures = set(EffectVerificationReason) - {EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE}

    decisions = {
        reason: decide_mscp_failure(reason, profile_mode=MscpProfileMode.GATING)
        for reason in failures
    }

    assert set(decisions) == failures
    assert all(decision.max_retry_attempts <= 1 for decision in decisions.values())
    assert all(decision.max_approval_requests <= 1 for decision in decisions.values())
    assert all(decision.demote_to_shadow for decision in decisions.values())
    assert all(not decision.execution_authority for decision in decisions.values())


@pytest.mark.parametrize(
    "reason",
    [
        EffectVerificationReason.PREDICTION_UNAVAILABLE,
        EffectVerificationReason.PREDICTION_PROVIDER_FAILED,
        EffectVerificationReason.PREDICTION_TARGET_MISMATCH,
    ],
)
def test_prediction_failures_hold_before_dispatch_with_one_bounded_request(
    reason: EffectVerificationReason,
) -> None:
    decision = decide_mscp_failure(reason, profile_mode=MscpProfileMode.SHADOW)

    assert decision.disposition is MscpFailureDisposition.HOLD_BEFORE_DISPATCH
    assert decision.retry_allowed(attempts_used=0) is True
    assert decision.retry_allowed(attempts_used=1) is False
    assert decision.approval_allowed(requests_used=0) is True
    assert decision.approval_allowed(requests_used=1) is False
    assert decision.demote_to_shadow is False


def test_mismatch_requires_recovery_without_retry_or_approval_fanout() -> None:
    decision = decide_mscp_failure(
        EffectVerificationReason.VALUE_OUTSIDE_ACCEPTABLE_RANGE,
        profile_mode=MscpProfileMode.GATING,
    )

    assert decision.disposition is MscpFailureDisposition.RECOVER_AFTER_DISPATCH
    assert decision.retry_allowed(attempts_used=0) is False
    assert decision.approval_allowed(requests_used=0) is False
    assert decision.demote_to_shadow is True


@pytest.mark.parametrize(
    "reason",
    [
        EffectVerificationReason.OBSERVATION_UNAVAILABLE,
        EffectVerificationReason.OBSERVATION_PROVIDER_FAILED,
        EffectVerificationReason.OBSERVATION_AFTER_DEADLINE,
        EffectVerificationReason.PREDICTION_ID_MISMATCH,
        EffectVerificationReason.TARGET_MISMATCH,
        EffectVerificationReason.METRIC_MISMATCH,
    ],
)
def test_observation_and_correlation_failures_hold_after_dispatch_without_fanout(
    reason: EffectVerificationReason,
) -> None:
    decision = decide_mscp_failure(reason, profile_mode=MscpProfileMode.GATING)

    assert decision.disposition is MscpFailureDisposition.HOLD_AFTER_DISPATCH
    assert decision.max_retry_attempts == 0
    assert decision.max_approval_requests == 0
    assert decision.demote_to_shadow is True


def test_success_reason_is_not_accepted_as_failure() -> None:
    with pytest.raises(ValueError, match="not an MSCP failure"):
        decide_mscp_failure(
            EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE,
            profile_mode=MscpProfileMode.SHADOW,
        )
