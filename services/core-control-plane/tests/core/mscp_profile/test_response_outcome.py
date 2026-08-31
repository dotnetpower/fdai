"""Response-outcome projection from expected and observed effects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.mscp_profile import (
    EffectVerificationReason,
    EffectVerificationResult,
    EffectVerificationStatus,
    ExpectedEffect,
    ObservedEffect,
    admissible_effect_evidence,
    build_response_outcome,
    response_outcome_audit_entry,
    verify_effect,
)
from fdai.shared.contracts.models import Action

_NOW = datetime(2026, 7, 30, tzinfo=UTC)


def _action() -> Action:
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "example-action-1",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type": "ops.scale-out",
            "target_resource_ref": "resource:example/rg/vm-a",
            "operation": "scale",
            "params": {},
            "stop_condition": "provider_api_error_streak",
            "stop_conditions": [{"kind": "provider_api_error_streak", "count": 3}],
            "rollback_ref": {"kind": "state_forward_only"},
            "blast_radius": {"scope": "resource", "count": 1},
            "mode": "shadow",
            "citing_rules": ["example.rule.x"],
            "created_at": _NOW,
        }
    )


def _expected() -> ExpectedEffect:
    return ExpectedEffect(
        prediction_id="prediction-1",
        target_ref=_action().target_resource_ref,
        metric="availability",
        acceptable_min=0.99,
        acceptable_max=1.0,
        predicted_at=_NOW,
        observation_deadline=_NOW + timedelta(minutes=5),
    )


def test_verified_effect_builds_scorable_privacy_minimized_audit() -> None:
    expected = _expected()
    observed = ObservedEffect(
        prediction_id=expected.prediction_id,
        target_ref=expected.target_ref,
        metric=expected.metric,
        value=0.995,
        observed_at=_NOW + timedelta(minutes=1),
    )
    outcome = build_response_outcome(
        action=_action(),
        execution_outcome="published",
        verification=EffectVerificationResult(
            EffectVerificationStatus.VERIFIED,
            EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE,
        ),
        expected=expected,
        observed=observed,
        recorded_at=_NOW + timedelta(minutes=2),
    )

    entry = response_outcome_audit_entry(outcome)
    assert entry["scorable"] is True
    assert entry["verification_passed"] is True
    assert entry["target_digest"]
    assert "target_resource_ref" not in entry


def test_missing_prediction_builds_unscorable_outcome() -> None:
    outcome = build_response_outcome(
        action=_action(),
        execution_outcome="published",
        verification=EffectVerificationResult(
            EffectVerificationStatus.HOLD,
            EffectVerificationReason.PREDICTION_UNAVAILABLE,
        ),
        recorded_at=_NOW,
    )

    entry = response_outcome_audit_entry(outcome)
    assert entry["label"] == "unscorable"
    assert entry["scorable"] is False
    assert "observed_at" not in entry


@pytest.mark.parametrize(
    ("observed_at", "recorded_at", "reason"),
    [
        (
            _NOW + timedelta(minutes=6),
            _NOW + timedelta(minutes=7),
            EffectVerificationReason.OBSERVATION_AFTER_DEADLINE,
        ),
        (
            _NOW - timedelta(minutes=1),
            _NOW + timedelta(minutes=2),
            EffectVerificationReason.OBSERVATION_BEFORE_PREDICTION,
        ),
        (
            _NOW + timedelta(minutes=2),
            _NOW + timedelta(minutes=1),
            EffectVerificationReason.OBSERVATION_NOT_YET_RECORDED,
        ),
    ],
)
def test_unrepresentable_observation_degrades_to_unscorable_instead_of_raising(
    observed_at: datetime,
    recorded_at: datetime,
    reason: EffectVerificationReason,
) -> None:
    """Out-of-window and not-yet-recorded evidence MUST fail closed, not raise.

    The verification comes from the real :func:`verify_effect`, so the
    not-yet-recorded case enters the projection exactly as the control loop
    produces it - ``verified`` on a value the prediction accepts - and the
    projection, not the caller, has to hold it.
    """

    expected = _expected()
    observed = ObservedEffect(
        prediction_id=expected.prediction_id,
        target_ref=expected.target_ref,
        metric=expected.metric,
        value=0.995,
        observed_at=observed_at,
    )
    verification = verify_effect(expected, observed)
    outcome = build_response_outcome(
        action=_action(),
        execution_outcome="published",
        verification=verification,
        expected=expected,
        observed=observed,
        recorded_at=recorded_at,
        decision="abstain",
    )

    entry = response_outcome_audit_entry(outcome)
    assert entry["label"] == "unscorable"
    assert entry["scorable"] is False
    assert entry["verification_passed"] is False
    assert entry["verification_status"] == "hold"
    assert entry["verification_reason"] == reason.value
    assert "observed_at" not in entry
    assert "observed_value" not in entry


def test_not_yet_recorded_observation_holds_a_verified_comparison() -> None:
    """A value the prediction accepts is still unusable before it is recorded."""

    expected = _expected()
    observed = ObservedEffect(
        prediction_id=expected.prediction_id,
        target_ref=expected.target_ref,
        metric=expected.metric,
        value=0.995,
        observed_at=_NOW + timedelta(minutes=2),
    )
    verification = verify_effect(expected, observed)
    assert verification.status is EffectVerificationStatus.VERIFIED

    held, admissible = admissible_effect_evidence(
        verification=verification,
        expected=expected,
        observed=observed,
        recorded_at=_NOW + timedelta(minutes=1),
    )

    assert admissible is None
    assert held.status is EffectVerificationStatus.HOLD
    assert held.reason is EffectVerificationReason.OBSERVATION_NOT_YET_RECORDED


def test_held_evidence_keeps_its_original_hold_reason() -> None:
    """A verdict already held MUST NOT be relabelled by the recording rule."""

    expected = _expected()
    observed = ObservedEffect(
        prediction_id=expected.prediction_id,
        target_ref="resource:example/rg/vm-b",
        metric=expected.metric,
        value=0.995,
        observed_at=_NOW + timedelta(minutes=2),
    )
    verification = verify_effect(expected, observed)
    assert verification.reason is EffectVerificationReason.TARGET_MISMATCH

    held, admissible = admissible_effect_evidence(
        verification=verification,
        expected=expected,
        observed=observed,
        recorded_at=_NOW + timedelta(minutes=1),
    )

    assert admissible is None
    assert held == verification
