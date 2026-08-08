"""Project effect verification into the shared response-outcome contract."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fdai.core.mscp_profile.effect_verification import (
    EffectVerificationResult,
    EffectVerificationStatus,
    ExpectedEffect,
    ObservedEffect,
)
from fdai.shared.contracts.models import (
    Action,
    ResponseOutcome,
    ResponseOutcomeLabel,
    ResponseVerificationStatus,
)


def build_response_outcome(
    *,
    action: Action,
    execution_outcome: str,
    verification: EffectVerificationResult,
    recorded_at: datetime,
    expected: ExpectedEffect | None = None,
    observed: ObservedEffect | None = None,
    decision: Literal["auto", "hil", "deny", "abstain"] = "auto",
    rollback_succeeded: bool | None = None,
) -> ResponseOutcome:
    """Build one replay-stable expected-versus-observed response record."""

    label = _label(verification.status, observed=observed)
    prediction_id = expected.prediction_id if expected is not None else None
    identity = f"{action.action_id}:{prediction_id or 'unavailable'}"
    outcome_id = uuid5(NAMESPACE_URL, f"fdai-response-outcome:{identity}")
    evidence_ref = (
        f"effect:{prediction_id}" if prediction_id is not None else f"action:{action.action_id}"
    )
    return ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=outcome_id,
        idempotency_key=f"response-outcome:{outcome_id}",
        action_id=action.action_id,
        event_id=action.event_id,
        action_type_id=action.action_type,
        target_digest=hashlib.sha256(action.target_resource_ref.encode()).hexdigest(),
        prediction_id=prediction_id,
        metric=expected.metric if expected is not None else None,
        expected_min=expected.acceptable_min if expected is not None else None,
        expected_max=expected.acceptable_max if expected is not None else None,
        observed_value=observed.value if observed is not None else None,
        predicted_at=expected.predicted_at if expected is not None else None,
        observation_deadline=(expected.observation_deadline if expected is not None else None),
        observed_at=observed.observed_at if observed is not None else None,
        label=label,
        verification_status=ResponseVerificationStatus(verification.status.value),
        verification_reason=verification.reason.value,
        execution_mode=action.mode,
        execution_outcome=execution_outcome,
        decision=decision,
        rollback_succeeded=rollback_succeeded,
        evidence_refs=(evidence_ref,),
        recorded_at=recorded_at,
    )


def response_outcome_audit_entry(outcome: ResponseOutcome) -> dict[str, object]:
    """Return the canonical audit projection consumed by measurement jobs."""

    payload = outcome.model_dump(mode="json", exclude_none=True)
    return {
        "actor": "fdai.measurement",
        "action_kind": "measurement.action_outcome.v1",
        "mode": outcome.execution_mode.value,
        **payload,
        "scorable": outcome.scorable,
        "verification_passed": outcome.verification_passed,
    }


def _label(
    status: EffectVerificationStatus,
    *,
    observed: ObservedEffect | None,
) -> ResponseOutcomeLabel:
    if status is EffectVerificationStatus.VERIFIED and observed is not None:
        return ResponseOutcomeLabel.VERIFIED
    if status is EffectVerificationStatus.MISMATCH and observed is not None:
        return ResponseOutcomeLabel.MISMATCH
    return ResponseOutcomeLabel.UNSCORABLE


__all__ = ["build_response_outcome", "response_outcome_audit_entry"]
