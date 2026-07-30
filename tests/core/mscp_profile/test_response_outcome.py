"""Response-outcome projection from expected and observed effects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.mscp_profile import (
    EffectVerificationReason,
    EffectVerificationResult,
    EffectVerificationStatus,
    ExpectedEffect,
    ObservedEffect,
    build_response_outcome,
    response_outcome_audit_entry,
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
