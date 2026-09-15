"""Pure alert effect comparisons bound to retained Actions and canonical dispatch lineage.

These records neither advance a Process nor authorize recovery. In particular, ``recovered``
means an independently observed configuration restore, not a released automation hold.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertEffectObservation
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.admission import effect_outcome
from fdai.core.detection.alert_noise.execution_models import RESTORE_ACTION, AlertExecutionHeld
from fdai.core.detection.alert_noise.outcome_lineage import (
    alert_effect_deadline as alert_effect_deadline,
)
from fdai.core.detection.alert_noise.outcome_lineage import (
    require_alert_dispatch_lineage as require_alert_dispatch_lineage,
)
from fdai.core.detection.alert_noise.outcome_models import (
    _DIGEST as _DIGEST,
)
from fdai.core.detection.alert_noise.outcome_models import (
    _REF as _REF,
)
from fdai.core.detection.alert_noise.outcome_models import (
    ALERT_EFFECT_PURPOSE as ALERT_EFFECT_PURPOSE,
)
from fdai.core.detection.alert_noise.outcome_models import (
    ALERT_RECOVERY_EFFECT_PURPOSE as ALERT_RECOVERY_EFFECT_PURPOSE,
)
from fdai.core.detection.alert_noise.outcome_models import (
    AlertEffectContext as AlertEffectContext,
)
from fdai.core.detection.alert_noise.outcome_models import (
    AlertEffectDrift as AlertEffectDrift,
)
from fdai.core.detection.alert_noise.outcome_models import (
    AlertEffectOutcome as AlertEffectOutcome,
)
from fdai.core.detection.alert_noise.outcome_models import (
    AlertEffectPurpose as AlertEffectPurpose,
)
from fdai.core.detection.alert_noise.outcome_models import (
    AlertExecutedActionRecord as AlertExecutedActionRecord,
)
from fdai.core.detection.alert_noise.outcome_models import (
    AlertExecutionNotice as AlertExecutionNotice,
)
from fdai.core.detection.alert_noise.outcome_models import (
    alert_effect_key as alert_effect_key,
)
from fdai.core.detection.alert_noise.outcome_models import (
    alert_executed_action_key as alert_executed_action_key,
)
from fdai.core.executor.safeguards import full_action_digest
from fdai.shared.contracts.models import (
    ResponseOutcome,
    ResponseOutcomeLabel,
    ResponseVerificationStatus,
)


def classify_alert_effect(
    context: AlertEffectContext,
    observation: AlertEffectObservation | None,
    *,
    now: datetime,
) -> AlertEffectOutcome:
    """Wrap the legacy pure classifier without letting its recovery flag create lineage.

    Short but adverse observations stop work immediately. Positive suppression evidence
    must cover activation AND post-expiry observation. Empty recovery samples cannot close
    recovery; missing, late, synthetic or mismatched context always stays held.
    """
    plan, action = context.execution.plan, context.execution.action
    if (
        now.tzinfo is None
        or now.utcoffset() is None
        or context.dispatched_at.tzinfo is None
        or context.dispatched_at.utcoffset() is None
    ):
        return "held"
    try:
        require_alert_dispatch_lineage(context)
    except (ValueError, TypeError):
        return "held"
    restore = action.action_type == RESTORE_ACTION
    if (
        observation is None
        or observation.recovery is not restore
        or observation.executor_ref != action.executor_identity_ref
        or not plan.created_at <= action.created_at <= context.dispatched_at <= now
        or context.execution.source_event.terminal_at > now
        or (not restore and not context.dispatched_at < plan.expires_at)
        or observation.window_end > alert_effect_deadline(context)
        or observation.recorded_at > alert_effect_deadline(context)
    ):
        return "held"
    result = effect_outcome(
        plan,
        observation,
        dispatch_ref=context.execution.dispatch_ref,
        dispatched_at=context.dispatched_at,
        now=now,
    )
    if result == "recovery_required":
        return "recovery_incomplete" if restore else "recovery_required"
    if result == "unscorable":
        return "recovery_incomplete" if restore else "unscorable"
    if result not in {"verified", "recovered"}:
        return "held"
    latest_start = context.dispatched_at + timedelta(
        seconds=plan.max_recovery_seconds if restore else plan.max_execution_seconds
    )
    starts, ends = plan.treatment.starts_at, plan.treatment.ends_at
    if not restore and starts is not None and ends is not None:
        if observation.window_start > starts or observation.window_end <= ends:
            return "held"
    if observation.window_start > latest_start:
        return "held"
    return "recovered" if restore else "verified"


def alert_response_outcome(
    context: AlertEffectContext,
    observation: AlertEffectObservation,
    *,
    receipt_digest: str,
    now: datetime,
) -> ResponseOutcome | None:
    """Compare the independently observed contract, never a provider return or savings estimate.

    The boolean metric is the complete effect contract (1), not notification reduction.
    Incomplete/empty evidence supplies no numeric observation. Recorded time and identity
    are evidence-derived, so replay does not create another response outcome.
    """
    result = classify_alert_effect(context, observation, now=now)
    if _DIGEST.fullmatch(receipt_digest) is None:
        raise AlertExecutionHeld("alert_effect_receipt_digest_invalid")
    if result == "held":
        return None
    verified = result in {"verified", "recovered"}
    regression = not all(
        (
            observation.configuration_matches,
            observation.collection_continues,
            observation.protected_paths_preserved,
            observation.response_deadlines_preserved,
        )
    )
    regression = regression or bool(observation.failures or observation.missed_incidents)
    measured = verified or regression
    label = (
        ResponseOutcomeLabel.VERIFIED
        if verified
        else ResponseOutcomeLabel.MISMATCH
        if measured
        else ResponseOutcomeLabel.UNSCORABLE
    )
    status = (
        ResponseVerificationStatus.VERIFIED
        if verified
        else ResponseVerificationStatus.MISMATCH
        if measured
        else ResponseVerificationStatus.HOLD
    )
    action, plan = context.execution.action, context.execution.plan
    identity = content_digest(
        {
            "action_digest": full_action_digest(action),
            "observation_digest": digest_record(observation),
            "receipt_digest": receipt_digest,
            "outcome": result,
        }
    )
    return ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=uuid5(NAMESPACE_URL, "fdai.alert-effect://" + identity),
        idempotency_key="alert-effect:" + identity,
        action_id=action.action_id,
        event_id=action.event_id,
        action_type_id=action.action_type,
        target_digest=hashlib.sha256(action.target_resource_ref.encode()).hexdigest(),
        prediction_id=digest_record(plan),
        metric="alert_effect_verified",
        expected_min=1.0,
        expected_max=1.0,
        observed_value=(1.0 if verified else 0.0) if measured else None,
        predicted_at=context.dispatched_at,
        observation_deadline=alert_effect_deadline(context),
        observed_at=observation.window_end if measured else None,
        label=label,
        verification_status=status,
        verification_reason="alert_noise." + result,
        execution_mode=action.mode,
        execution_outcome=context.execution.execution_outcome,
        decision="hil",
        rollback_succeeded=True if result == "recovered" else None,
        evidence_refs=(
            alert_effect_key(
                plan_digest=digest_record(plan), dispatch_ref=context.execution.dispatch_ref
            ),
            receipt_digest,
            observation.receipt_ref,
            context.safeguard_bundle_digest,
        ),
        recorded_at=observation.recorded_at,
    )
