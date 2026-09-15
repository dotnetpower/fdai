"""Relay retained Thor references with restart-safe paging and consumer-progress markers.

Helpers use the runtime's existing adapters and callbacks; they retain no second cursor,
clock, lock or workflow state. Publication remains at-least-once, not effect verification.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_base import AlertTime
from fdai_service_contracts.alert_noise_plan import AlertEffectObservation
from fdai_service_contracts.decision_evidence import DecisionCriticalEvidenceReceipt
from fdai_service_contracts.ontology_query import content_digest
from pydantic import TypeAdapter

from fdai.core.detection.alert_noise.execution import RESTORE_ACTION, AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    ALERT_RECOVERY_EFFECT_PURPOSE,
    AlertEffectContext,
    AlertExecutedActionRecord,
    alert_effect_deadline,
    alert_effect_key,
    alert_executed_action_key,
)
from fdai.delivery.alert_noise_effects import read_alert_execution
from fdai.delivery.alert_noise_evidence import alert_scope_digest, exact_alert_model
from fdai.shared.providers.process_runtime import ProcessEventKind, ProcessStatus
from fdai.shared.providers.resource_lock import resource_lock_key

if TYPE_CHECKING:
    from fdai.runtime.alert_noise_effect_runtime import AlertEffectRuntime

_PREFIX = "alert-noise:executed-action:"
_TIME: TypeAdapter[datetime] = TypeAdapter(AlertTime)


async def _tick(runtime: AlertEffectRuntime) -> int:
    """Scan one bounded page and retain the same growth/tail cursor even on interruption."""
    async with (
        asyncio.timeout(45),
        runtime._tick_lock,
        runtime._lock.acquire(resource_lock_key(runtime._cursor_key)),
    ):
        runtime._current()
        retained_cursor = await runtime._store.read_state(runtime._cursor_key)
        cursor = {"offset": 0, "total": 0} if retained_cursor is None else retained_cursor
        if set(cursor) != {"offset", "total"} or any(
            type(value) is not int or value < 0 for value in cursor.values()
        ):
            raise AlertExecutionHeld("alert_effect_cursor_invalid")
        offset, previous = cursor["offset"], cursor["total"]
        rows, total = await runtime._store.read_state_page(_PREFIX, limit=100, offset=offset)
        if len(rows) > 100 or type(total) is not int or total < 0:
            raise AlertExecutionHeld("alert_effect_page_invalid")
        completed = published = 0
        try:
            async with asyncio.timeout(40):
                for raw in rows:
                    execution: AlertExecutedActionRecord | None = None
                    try:
                        async with asyncio.timeout(5):
                            execution = exact_alert_model(AlertExecutedActionRecord, dict(raw))
                            published += await runtime._notice(execution)
                    except Exception as exc:
                        await runtime._held(
                            "tick",
                            exc,
                            action_digest=execution.source_event.action_digest
                            if execution
                            else None,
                            correlation_id=(
                                execution.source_event.correlation_id if execution else None
                            ),
                        )
                    completed += 1
        finally:
            if not rows:
                next_offset = max(0, total - 100) if offset > total else 0
            elif offset + completed >= total:
                next_offset = 0
            else:
                next_offset = offset + completed + (max(0, total - previous) if offset else 0)
            async with asyncio.timeout(5):
                await runtime._store.write_state(
                    runtime._cursor_key, {"offset": next_offset, "total": total}
                )
        return published


def _settled(runtime: AlertEffectRuntime, context: AlertEffectContext) -> bool:
    """Historical canonical consumption survives source expiry without claiming fresh success."""
    execution, now = context.execution, runtime._current()
    lineage = execution.action.workflow_action
    for row in context.process_events:
        if (
            row.correlation_id != execution.source_event.correlation_id
            or not execution.source_event.terminal_at <= row.recorded_at <= now
        ):
            continue
        payload = row.payload
        if (
            row.kind is ProcessEventKind.STEP_COMPLETED
            and lineage is not None
            and row.step_id == lineage.step_id
            and row.attempt == lineage.attempt
            and payload.get("reason") == "action_effect_verified"
            and payload.get("safeguard_bundle_digest") == context.safeguard_bundle_digest
        ):
            return True
        if (
            row.kind is ProcessEventKind.COMPENSATION_COMPLETED
            and execution.action.action_type == RESTORE_ACTION
            and context.safeguard_bundle_digest in payload.get("safeguard_bundle_digests", ())
        ):
            return True
        if (
            row.kind is ProcessEventKind.EVIDENCE_ATTACHED
            and payload.get("actor_agent") == "Forseti"
            and payload.get("phase") == "outcome_recorded"
            and payload.get("execution_ref")
            == alert_executed_action_key(execution.source_event.action_digest)
            and payload.get("source_revision") == runtime._revision
            and payload.get("safeguard_bundle_digest") == context.safeguard_bundle_digest
            and (
                payload.get("recovery_required") is True
                or payload.get("process_status")
                in {ProcessStatus.SUCCEEDED.value, ProcessStatus.COMPENSATED.value}
            )
        ):
            return True
    return False


async def _notice(runtime: AlertEffectRuntime, execution: AlertExecutedActionRecord) -> int:
    """Publish one retained reference, checkpointing only after bus acceptance."""
    digest = execution.source_event.action_digest
    retained, reader = await runtime._execution(digest)
    context = await reader.read_context(action_digest=digest)
    if retained != execution or context is None or context.execution != execution:
        raise AlertExecutionHeld("alert_effect_context_changed")
    if runtime._settled(context):
        return 0
    raw = await runtime._store.read_state(
        alert_effect_key(
            plan_digest=digest_record(execution.plan), dispatch_ref=execution.dispatch_ref
        )
    )
    receipt = runtime._notification_receipt(context, raw)
    expired = runtime._current() >= alert_effect_deadline(context)
    if receipt is None and not expired:
        return 0
    identity = {
        "execution_ref": alert_executed_action_key(digest),
        "source_revision": runtime._revision,
        "publication_receipt": execution.model_dump(mode="json")["publication_receipt"],
        "dispatch_generation": execution.dispatch_generation,
        "effect_receipt_digest": receipt,
        "deadline": alert_effect_deadline(context).isoformat(),
    }
    token = content_digest(identity)
    marker = "alert-noise:effect-published:" + token
    previous = await runtime._store.read_state(marker)
    if previous is not None:
        if previous != identity:
            raise AlertExecutionHeld("alert_effect_publication_marker_conflict")
        if not expired:
            return 0
    current_effect = await runtime._store.read_state(
        alert_effect_key(
            plan_digest=digest_record(execution.plan), dispatch_ref=execution.dispatch_ref
        )
    )
    if not expired and runtime._notification_receipt(context, current_effect) != receipt:
        return 0
    if await read_alert_execution(runtime._store, digest) != execution:
        raise AlertExecutionHeld("alert_effect_execution_changed")
    runtime._current()
    await runtime._publish(
        "Thor",
        "object.action-run",
        {
            **execution.source_event.model_dump(mode="json"),
            "kind": "alert_noise_publication",
            "idempotency_key": "alert-noise-effect:" + token,
            "resource_id": execution.action.target_resource_ref,
        },
    )
    if not await runtime._store.write_state_if_absent(marker, identity):
        if await runtime._store.read_state(marker) != identity:
            raise AlertExecutionHeld("alert_effect_publication_marker_conflict")
    return 1


def _notification_receipt(
    runtime: AlertEffectRuntime, context: AlertEffectContext, raw: Mapping[str, Any] | None
) -> str | None:
    """A matching record is a wake-up cue ONLY; the Heimdall reader still admits it."""
    try:
        if raw is None or set(raw) != {"payload", "receipt"}:
            return None
        payload, execution = raw["payload"], context.execution
        if set(payload) != {
            "observation",
            "action_digest",
            "dispatch_ref",
            "dispatched_at",
            "safeguard_bundle_digest",
        }:
            return None
        observation = exact_alert_model(AlertEffectObservation, payload["observation"])
        receipt = exact_alert_model(DecisionCriticalEvidenceReceipt, raw["receipt"])
        plan = execution.plan
        binding = runtime._bindings[(plan.tenant_ref, plan.scope_ref)]
        if (
            payload["action_digest"] != execution.source_event.action_digest
            or payload["dispatch_ref"] != execution.dispatch_ref
            or _TIME.validate_python(payload["dispatched_at"]) != context.dispatched_at
            or payload["safeguard_bundle_digest"] != context.safeguard_bundle_digest
            or observation.plan_digest != digest_record(plan)
            or observation.dispatch_ref != execution.dispatch_ref
            or observation.recovery is not (context.purpose == ALERT_RECOVERY_EFFECT_PURPOSE)
            or any(
                getattr(observation, key) != binding[key]
                for key in ("source_ref", "observer_ref", "executor_ref")
            )
            or observation.synthetic
            or receipt.synthetic
            or receipt.execution_authority is not False
            or receipt.evidence_digest != content_digest(payload)
            or receipt.source_revision != runtime._revision
            or receipt.scope_digest
            != alert_scope_digest(tenant_ref=plan.tenant_ref, scope_ref=plan.scope_ref)
            or receipt.source_identity != binding["identities"][binding["source_ref"]]
            or receipt.authority_class != binding["authority_class"]
            or receipt.purpose_id != context.purpose
        ):
            return None
        return receipt.receipt_digest
    except (ValueError, TypeError, KeyError):
        return None
