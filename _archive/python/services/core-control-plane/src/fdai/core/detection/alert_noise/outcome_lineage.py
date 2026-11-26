"""Pure canonical dispatch-lineage and observation-deadline checks for alert effects."""

from __future__ import annotations

from datetime import datetime, timedelta

from fdai.core.detection.alert_noise.execution_models import RESTORE_ACTION, AlertExecutionHeld
from fdai.core.detection.alert_noise.outcome_models import (
    _DIGEST,
    ALERT_EFFECT_PURPOSE,
    ALERT_RECOVERY_EFFECT_PURPOSE,
    AlertEffectContext,
)
from fdai.core.workflow.workflow_runtime import event_id
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind


def require_alert_dispatch_lineage(context: AlertEffectContext) -> ProcessEvent:
    """Require an exact canonical dispatch and, for restore, its real forward predecessor.

    Post-failed-compensation recover_* attempts need the richer WorkflowRecoveryCoordinator
    claim/hold/watermark contracts. They deliberately cannot impersonate compensation here.
    """
    action = context.execution.action
    lineage = action.workflow_action
    if (
        lineage is None
        or len(context.process_events) > 2048
        or _DIGEST.fullmatch(context.safeguard_bundle_digest) is None
    ):
        raise AlertExecutionHeld("alert_effect_lineage_missing")
    restore = action.action_type == RESTORE_ACTION
    expected_purpose = ALERT_RECOVERY_EFFECT_PURPOSE if restore else ALERT_EFFECT_PURPOSE
    kind = (
        ProcessEventKind.COMPENSATION_DISPATCHED if restore else ProcessEventKind.ACTION_DISPATCHED
    )
    if context.purpose != expected_purpose:
        raise AlertExecutionHeld("alert_effect_purpose_mismatch")
    events = context.process_events
    matches = tuple(
        row
        for row in events
        if row.kind is kind and row.step_id == lineage.step_id and row.attempt == lineage.attempt
    )
    if len(matches) != 1:
        raise AlertExecutionHeld("alert_effect_dispatch_missing")
    dispatch = matches[0]
    expected: dict[str, object] = {
        "proposal_ref": lineage.proposal_ref,
        "action_type": action.action_type,
    }
    suffix = f"step:{lineage.step_id}:attempt:{lineage.attempt}:action-dispatched"
    if restore:
        original_step = lineage.step_id.removeprefix("compensate_")
        if original_step == lineage.step_id:
            raise AlertExecutionHeld("alert_effect_recovery_coordinator_required")
        expected["compensates_step_id"] = original_step
        suffix = f"compensation:{original_step}:dispatched"
        prior = events[: events.index(dispatch)]
        intents = tuple(
            row
            for row in prior
            if row.kind is ProcessEventKind.COMPENSATION_STARTED
            and row.step_id == lineage.step_id
            and row.attempt == lineage.attempt
        )
        completed = tuple(
            row
            for row in prior
            if row.kind is ProcessEventKind.STEP_COMPLETED
            and row.step_id == original_step
            and row.payload.get("reason") == "action_effect_verified"
        )
        if len(intents) != 1 or len(completed) != 1:
            raise AlertExecutionHeld("alert_effect_recovery_lineage_missing")
        intent, forward = intents[0], completed[0]
        bundle = forward.payload.get("safeguard_bundle_digest")
        originals = tuple(
            row
            for row in prior[: prior.index(forward)]
            if row.kind is ProcessEventKind.ACTION_DISPATCHED
            and row.step_id == original_step
            and row.attempt == forward.attempt
            and row.payload.get("params") == action.params
            and row.payload.get("action_type") == context.execution.plan.action_type
        )
        if (
            len(originals) != 1
            or prior.index(forward) >= prior.index(intent)
            or type(bundle) is not str
            or _DIGEST.fullmatch(bundle) is None
            or bundle == context.safeguard_bundle_digest
            or intent.payload.get("original_safeguard_bundle_digest") != bundle
            or intent.payload.get("compensates_step_id") != original_step
            or intent.payload.get("action_type") != RESTORE_ACTION
            or intent.payload.get("params") != action.params
            or any(
                row.process_id != lineage.process_id
                or row.correlation_id != dispatch.correlation_id
                for row in (*originals, forward, intent)
            )
            or not originals[0].recorded_at
            <= forward.recorded_at
            <= intent.recorded_at
            <= dispatch.recorded_at
        ):
            raise AlertExecutionHeld("alert_effect_recovery_predecessor_mismatch")
    else:
        expected["params"] = dict(action.params)
    if (
        dispatch.process_id != lineage.process_id
        or dispatch.event_id != event_id(lineage.process_id, suffix)
        or dispatch.idempotency_key != f"{lineage.process_id}:{suffix}"
        or dispatch.correlation_id != context.execution.source_event.correlation_id
        or dispatch.payload != expected
        or not dispatch.recorded_at
        <= context.dispatched_at
        <= context.execution.source_event.terminal_at
    ):
        raise AlertExecutionHeld("alert_effect_dispatch_mismatch")
    return dispatch


def alert_effect_deadline(context: AlertEffectContext) -> datetime:
    """Bound observed/recorded time; restoration never borrows expired forward authority."""
    plan = context.execution.plan
    restore = context.execution.action.action_type == RESTORE_ACTION
    budget = plan.max_recovery_seconds if restore else plan.max_execution_seconds
    deadline = context.dispatched_at + timedelta(seconds=budget + plan.max_observation_seconds)
    if not restore:
        if plan.treatment.ends_at is not None:
            deadline = max(
                deadline,
                plan.treatment.ends_at + timedelta(seconds=plan.max_recovery_seconds),
            )
        deadline = min(deadline, plan.expires_at)
    return deadline
