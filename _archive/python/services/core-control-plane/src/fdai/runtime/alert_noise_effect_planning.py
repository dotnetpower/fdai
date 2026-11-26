"""Plan admitted effect outcomes through existing workflow resume and logical-target holds.

The runtime retains adapters and state. These private steps neither dispatch recovery nor
release holds, and keep every evidence recheck at its original invocation boundary.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import AlertEffectDrift
from fdai.core.workflow.workflow_runtime import event_id
from fdai.shared.providers.process_runtime import ProcessEventKind, ProcessStatus
from fdai.shared.providers.resource_lock import resource_lock_key

if TYPE_CHECKING:
    from fdai.runtime.alert_noise_effect_runtime import AlertEffectRuntime

_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")


async def _plan(runtime: AlertEffectRuntime, signal: AlertEffectDrift) -> dict[str, Any]:
    """Consume the exact journal before recording holds or resuming an observed final step."""
    context, resolution, journal, admitted = await runtime._resolve(signal)
    if signal.effect_outcome not in {"verified", "recovered"}:
        if signal.effect_outcome == "held":
            return {"status": "held", "recovery_required": False, "execution_authority": False}
        prior = next(
            (
                row
                for row in resolution.events
                if row.kind is ProcessEventKind.EVIDENCE_ATTACHED
                and row.payload.get("actor_agent") == "Forseti"
                and row.payload.get("evidence_ref") == signal.outcome_ref
                and row.payload.get("recovery_required") is True
            ),
            None,
        )
        if prior is not None:
            prior_digests = prior.payload.get("automation_hold_receipt_digests")
            if (
                type(prior_digests) is not list
                or not 1 <= len(prior_digests) <= 256
                or any(
                    type(value) is not str or _DIGEST.fullmatch(value) is None
                    for value in prior_digests
                )
            ):
                raise AlertExecutionHeld("alert_effect_planning_child_conflict")
            suffix = "alert-effect-plan:" + content_digest(
                {
                    "outcome_ref": signal.outcome_ref,
                    "recovery_required": True,
                    "hold_receipt_digests": prior_digests,
                    "process_status": None,
                }
            )
            if (
                prior.event_id != event_id(signal.process_id, suffix)
                or prior.idempotency_key != f"{signal.process_id}:{suffix}"
            ):
                raise AlertExecutionHeld("alert_effect_planning_child_conflict")
            await runtime._child(
                signal, context, recovery_required=True, hold_digests=prior_digests
            )
            # A delayed duplicate must never reissue a separately released hold.
            active = []
            for ref in context.execution.plan.lock_refs:
                if await runtime._holds.read_hold_record(target_ref=ref) is None:
                    raise AlertExecutionHeld("alert_effect_hold_unavailable")
                active.append(await runtime._holds.is_held(target_ref=ref))
            return {
                "status": "already_recorded",
                "recovery_required": any(active),
                "effect_outcome": signal.effect_outcome,
                "execution_authority": False,
            }
        digests: list[str] = []
        target = context.execution.action.target_resource_ref
        # Each dependency is its own logical target, NEVER one composite lock key.
        for ref in (target, *(ref for ref in context.execution.plan.lock_refs if ref != target)):
            await runtime._unchanged(signal, context, resolution, journal)
            await runtime._holds.issue(
                target_ref=ref,
                process_id=signal.process_id,
                reason="alert_noise." + signal.effect_outcome,
            )
            hold = await runtime._holds.read_hold_record(target_ref=ref)
            if hold is None or hold.get("state") != "active":
                raise AlertExecutionHeld("alert_effect_hold_unavailable")
            if hold.get("process_id") != signal.process_id:
                raise AlertExecutionHeld("alert_effect_hold_owner_conflict")
            digests.append(content_digest(dict(hold)))
        await runtime._unchanged(signal, context, resolution, journal)
        await runtime._child(signal, context, recovery_required=True, hold_digests=digests)
        return {
            "status": "recovery_required",
            "effect_outcome": signal.effect_outcome,
            "recovery_required": True,
            "execution_authority": False,
        }
    if admitted is None or signal.workflow_outcome_ref is None:
        raise AlertExecutionHeld("alert_effect_workflow_admission_missing")
    await runtime._positive(signal, context, admitted)
    for ref in context.execution.plan.lock_refs:
        if await runtime._holds.is_held(target_ref=ref):
            hold = await runtime._holds.read_hold_record(target_ref=ref)
            if hold is None:
                raise AlertExecutionHeld("alert_effect_hold_unavailable")
            await runtime._child(
                signal, context, recovery_required=True, hold_digests=[content_digest(dict(hold))]
            )
            return {
                "status": "recovery_required",
                "reason": "separate_recovery_approval_required",
                "recovery_required": True,
                "execution_authority": False,
            }
    terminal = (
        ProcessStatus.COMPENSATED
        if signal.effect_outcome == "recovered"
        else ProcessStatus.SUCCEEDED
    )
    if resolution.snapshot.status.terminal:
        if resolution.snapshot.status is not terminal:
            raise AlertExecutionHeld("alert_effect_workflow_terminal_mismatch")
        await runtime._child(
            signal,
            context,
            recovery_required=False,
            hold_digests=[],
            process_status=resolution.snapshot.status,
        )
        return {
            "status": "already_terminal",
            "process_status": resolution.snapshot.status.value,
            "execution_authority": False,
        }
    expected = (
        ProcessStatus.COMPENSATING
        if signal.effect_outcome == "recovered"
        else ProcessStatus.WAITING
    )
    if (
        resolution.snapshot.status is not expected
        or resolution.snapshot.current_step != signal.step_id
        or (
            signal.effect_outcome == "verified"
            and any(
                row.kind is ProcessEventKind.PROCESS_CANCELLATION_REQUESTED
                for row in resolution.events
            )
        )
        or any(
            row.kind is ProcessEventKind.COMPENSATION_STARTED
            and not any(
                dispatched.kind is ProcessEventKind.COMPENSATION_DISPATCHED
                and dispatched.step_id == row.step_id
                and dispatched.attempt == row.attempt
                for dispatched in resolution.events
            )
            for row in resolution.events
        )
    ):
        raise AlertExecutionHeld("alert_effect_process_not_at_observation_boundary")
    # Serialize with hold issuance; canonical resume has no undispatched step
    # at this exact two-step workflow boundary and may only consume its outcome.
    async with runtime._lock.acquire(resource_lock_key(signal.resource_id)):
        if await runtime._holds.is_held(target_ref=signal.resource_id):
            raise AlertExecutionHeld("alert_effect_target_held")
        await runtime._unchanged(signal, context, resolution, journal)
        await runtime._positive(signal, context, admitted)
        await runtime._unchanged(signal, context, resolution, journal)
        admitted.record.require_current(now=runtime._current())
        runtime._current()
        result = await runtime._workflows.resume(process_id=signal.process_id)
    if result.status is not terminal:
        raise AlertExecutionHeld("alert_effect_workflow_terminal_mismatch")
    # Receipt of the Drift is not acknowledgement of Process completion.
    await runtime._child(
        signal, context, recovery_required=False, hold_digests=[], process_status=result.status
    )
    return {
        "status": "resumed",
        "process_status": result.status.value,
        "effect_outcome": signal.effect_outcome,
        "recovery_required": False,
        "execution_authority": False,
    }
