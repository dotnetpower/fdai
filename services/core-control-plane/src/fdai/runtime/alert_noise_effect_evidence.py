"""Resolve exact Heimdall journals and retain Forseti evidence children without deciding effects."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    AlertEffectContext,
    AlertEffectDrift,
    alert_executed_action_key,
    alert_response_outcome,
    require_alert_dispatch_lineage,
)
from fdai.core.detection.alert_noise.workflow import AlertWorkflowResolution
from fdai.core.workflow.workflow_runtime import event_id
from fdai.delivery.alert_noise_effects import (
    AdmittedAlertEffect,
    alert_effect_journal,
    alert_missing_effect_journal,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind, ProcessStatus

if TYPE_CHECKING:
    from fdai.runtime.alert_noise_effect_runtime import AlertEffectRuntime

_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")


async def _resolve(
    runtime: AlertEffectRuntime, signal: AlertEffectDrift
) -> tuple[AlertEffectContext, AlertWorkflowResolution, dict[str, Any], AdmittedAlertEffect | None]:
    """Reconstruct the journal and its exact child against the newest retained dispatch."""
    if (
        not signal.outcome_ref.startswith("alert-noise:outcome:")
        or _DIGEST.fullmatch(signal.outcome_ref.removeprefix("alert-noise:outcome:")) is None
    ):
        raise AlertExecutionHeld("alert_effect_outcome_reference_invalid")
    execution, reader = await runtime._execution(signal.action_digest)
    context = await reader.read_context(action_digest=signal.action_digest)
    lineage = execution.action.workflow_action
    if context is None or context.execution != execution or lineage is None:
        raise AlertExecutionHeld("alert_effect_context_changed")
    dispatch = require_alert_dispatch_lineage(context)
    latest = tuple(
        row
        for row in context.process_events
        if row.kind is dispatch.kind and row.step_id == dispatch.step_id
    )
    if not latest or latest[-1] != dispatch:
        raise AlertExecutionHeld("alert_effect_dispatch_superseded")
    if (
        signal.process_id != lineage.process_id
        or signal.step_id != lineage.step_id
        or signal.resource_id != execution.action.target_resource_ref
        or signal.correlation_id != execution.source_event.correlation_id
        or signal.plan_digest != digest_record(execution.plan)
        or signal.dispatch_ref != execution.dispatch_ref
    ):
        raise AlertExecutionHeld("alert_effect_signal_mismatch")
    resolution = await runtime._workflows.resolve(process_id=signal.process_id)
    if (
        resolution.plan != execution.plan
        or resolution.binding.source_revision != runtime._revision
        or resolution.binding.mode is not Mode.ENFORCE
        or resolution.snapshot.target_resource_id != signal.resource_id
        or resolution.snapshot.correlation_id != signal.correlation_id
        or not resolution.snapshot.started_at
        <= resolution.snapshot.updated_at
        <= runtime._current()
    ):
        raise AlertExecutionHeld("alert_effect_workflow_binding_mismatch")
    raw = await runtime._store.read_state(signal.outcome_ref)
    if raw is None:
        raise AlertExecutionHeld("alert_effect_outcome_missing")
    journal = dict(raw)
    admitted: AdmittedAlertEffect | None = None
    if journal.get("evidence_status") == "unknown":
        expected = alert_missing_effect_journal(
            context, source_revision=runtime._revision, recorded_at=signal.recorded_at
        )
        identity = {
            key: expected[key]
            for key in (
                "execution_ref",
                "source_revision",
                "observation_deadline",
                "safeguard_bundle_digest",
                "publication_receipt_digest",
            )
        }
        if (
            await runtime._store.read_state(
                "alert-noise:missing-effect:" + content_digest(identity)
            )
            != expected
        ):
            raise AlertExecutionHeld("alert_effect_missing_journal_mismatch")
    else:
        admitted = await reader.read_admitted(execution.plan, dispatch_ref=execution.dispatch_ref)
        if (
            admitted is None
            or admitted.context.execution != execution
            or admitted.observation.recorded_at != signal.recorded_at
        ):
            raise AlertExecutionHeld("alert_effect_admission_missing")
        expected = alert_effect_journal(admitted, now=runtime._current())
    suffix = "alert-effect:" + content_digest(expected)
    child = ProcessEvent(
        event_id=event_id(signal.process_id, suffix),
        process_id=signal.process_id,
        kind=ProcessEventKind.EVIDENCE_ATTACHED,
        idempotency_key=f"{signal.process_id}:{suffix}",
        recorded_at=signal.recorded_at,
        correlation_id=signal.correlation_id,
        causation_id=require_alert_dispatch_lineage(context).event_id,
        step_id=lineage.step_id,
        attempt=lineage.attempt,
        payload={
            "actor_agent": "Heimdall",
            "domain": "alert_noise",
            "evidence_ref": signal.outcome_ref,
            "independent_observation_ref": expected["effect_ref"] if admitted else None,
            "execution_authority": False,
        },
    )
    if (
        journal != expected
        or signal.outcome_ref != "alert-noise:outcome:" + content_digest(expected)
        or signal.idempotency_key != suffix
        or signal.effect_outcome != expected["effect_outcome"]
        or signal.recorded_at > runtime._current()
        or child not in context.process_events
        or (
            signal.effect_outcome not in {"verified", "recovered"}
            and signal.workflow_outcome_ref is not None
        )
    ):
        raise AlertExecutionHeld("alert_effect_outcome_journal_mismatch")
    await runtime._unchanged(signal, context, resolution, journal)
    return context, resolution, journal, admitted


async def _positive(
    runtime: AlertEffectRuntime,
    signal: AlertEffectDrift,
    context: AlertEffectContext,
    admitted: AdmittedAlertEffect,
) -> None:
    """Require the separate current workflow admission after exact response/publication matching."""
    response = alert_response_outcome(
        context,
        admitted.observation,
        receipt_digest=admitted.record.receipt_digest,
        now=runtime._current(),
    )
    record = await runtime._store.find_state(
        "workflow:outcome:", field="receipt_ref", value=signal.workflow_outcome_ref or ""
    )
    execution = context.execution
    if (
        response is None
        or record is None
        or record.get("response_outcome_id") != str(response.outcome_id)
        or record.get("action_id") != str(execution.action.action_id)
        or record.get("process_id") != signal.process_id
        or record.get("step_id") != signal.step_id
        or record.get("proposal_ref") != signal.dispatch_ref
        or record.get("outcome") != "succeeded"
        or record.get("evidence_status") != "effect_verified"
        or record.get("execution_outcome") != execution.execution_outcome
        or record.get("execution_receipt_ref") != execution.publication_receipt.pr_ref
        or record.get("safeguard_bundle_digest") != context.safeguard_bundle_digest
    ):
        raise AlertExecutionHeld("alert_effect_workflow_outcome_mismatch")
    await admitted.record.require_unchanged(runtime._store)
    admitted.record.require_current(now=runtime._current())
    # Resolve the independent workflow admission last, never create it in this callback.
    verified = await runtime._outcomes.resolve(
        process_id=signal.process_id, step_id=signal.step_id, proposal_ref=signal.dispatch_ref
    )
    if (
        verified is None
        or verified.outcome != "succeeded"
        or verified.receipt_ref != signal.workflow_outcome_ref
        or verified.safeguard_bundle_digest != context.safeguard_bundle_digest
    ):
        raise AlertExecutionHeld("alert_effect_workflow_admission_missing")
    admitted.record.require_current(now=runtime._current())


async def _unchanged(
    runtime: AlertEffectRuntime,
    signal: AlertEffectDrift,
    context: AlertEffectContext,
    resolution: AlertWorkflowResolution,
    journal: Mapping[str, Any],
) -> None:
    """Re-read execution, journal and Process snapshot at the existing await boundaries."""
    execution, _ = await runtime._execution(signal.action_digest)
    if (
        execution != context.execution
        or await runtime._store.read_state(signal.outcome_ref) != journal
        or await runtime._processes.get(signal.process_id) != resolution.snapshot
    ):
        raise AlertExecutionHeld("alert_effect_process_or_journal_changed")
    runtime._current()


async def _child(
    runtime: AlertEffectRuntime,
    signal: AlertEffectDrift,
    context: AlertEffectContext,
    *,
    recovery_required: bool,
    hold_digests: list[str],
    process_status: ProcessStatus | None = None,
) -> None:
    """Append the same replay-stable Forseti evidence child, never a Process transition."""
    suffix = "alert-effect-plan:" + content_digest(
        {
            "outcome_ref": signal.outcome_ref,
            "recovery_required": recovery_required,
            "hold_receipt_digests": hold_digests,
            "process_status": process_status.value if process_status else None,
        }
    )
    lineage = context.execution.action.workflow_action
    if lineage is None:
        raise AlertExecutionHeld("alert_effect_lineage_missing")
    prior = tuple(
        row
        for row in await runtime._processes.events(signal.process_id)
        if row.idempotency_key == f"{signal.process_id}:{suffix}"
    )
    at = prior[0].recorded_at if prior else runtime._current()
    if len(prior) > 1 or not signal.recorded_at <= at <= runtime._current():
        raise AlertExecutionHeld("alert_effect_planning_time_invalid")
    child = ProcessEvent(
        event_id=event_id(signal.process_id, suffix),
        process_id=signal.process_id,
        kind=ProcessEventKind.EVIDENCE_ATTACHED,
        idempotency_key=f"{signal.process_id}:{suffix}",
        recorded_at=at,
        correlation_id=signal.correlation_id,
        causation_id=event_id(signal.process_id, signal.idempotency_key),
        step_id=signal.step_id,
        attempt=lineage.attempt,
        payload={
            "actor_agent": "Forseti",
            "domain": "alert_noise",
            "phase": "outcome_recorded",
            "evidence_ref": signal.outcome_ref,
            "effect_outcome": signal.effect_outcome,
            "execution_ref": alert_executed_action_key(signal.action_digest),
            "source_revision": runtime._revision,
            "safeguard_bundle_digest": context.safeguard_bundle_digest,
            "process_status": process_status.value if process_status else None,
            "recovery_required": recovery_required,
            "automation_hold_receipt_digests": hold_digests,
            "execution_authority": False,
            "process_completed": False,
        },
    )
    if prior:
        if prior != (child,):
            raise AlertExecutionHeld("alert_effect_planning_child_conflict")
        return
    await runtime._processes.append_event(child)
    if child not in await runtime._processes.events(signal.process_id):
        raise AlertExecutionHeld("alert_effect_planning_child_conflict")
