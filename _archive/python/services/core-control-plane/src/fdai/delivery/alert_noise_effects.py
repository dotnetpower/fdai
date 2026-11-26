"""Read admitted effects and journal Heimdall observations without advancing workflows.

Bind real Core-owned stores, independent DE admission, configured identity mappings and
the schema-validating Pantheon bus publish method. Nothing here writes source evidence,
promotes a source, dispatches a restore, releases a hold or calls a WorkflowOrchestrator.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_base import AlertTime
from fdai_service_contracts.ontology_query import content_digest
from pydantic import TypeAdapter

from fdai.core.detection.alert_noise.execution import RESTORE_ACTION, AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    AlertEffectContext,
    AlertEffectDrift,
    AlertExecutionNotice,
    alert_effect_deadline,
    alert_response_outcome,
    classify_alert_effect,
    require_alert_dispatch_lineage,
)
from fdai.core.executor.safeguards import full_action_digest
from fdai.core.workflow.outcome_verification import StateStoreWorkflowOutcomeLedger
from fdai.core.workflow.workflow_runtime import event_id
from fdai.delivery.alert_noise_effect_reader import (
    StateStoreAlertEffectReader as StateStoreAlertEffectReader,
)
from fdai.delivery.alert_noise_effect_records import (
    AdmittedAlertEffect as AdmittedAlertEffect,
)
from fdai.delivery.alert_noise_effect_records import (
    AlertEffectPublish as AlertEffectPublish,
)
from fdai.delivery.alert_noise_effect_records import (
    alert_effect_journal as alert_effect_journal,
)
from fdai.delivery.alert_noise_effect_records import (
    alert_missing_effect_journal as alert_missing_effect_journal,
)
from fdai.delivery.alert_noise_effect_records import (
    read_alert_execution as read_alert_execution,
)
from fdai.delivery.alert_noise_evidence import AdmittedAlertRecord
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
)
from fdai.shared.providers.state_store import StateStore

_TIME: TypeAdapter[datetime] = TypeAdapter(AlertTime)


class HeimdallAlertEffectHandler:
    """Consume authenticated Thor references and publish only owned observation evidence.

    ``publish`` MUST be the composition-owned, schema-validating Pantheon bus publisher.
    ``handle`` returns journal/publication acceptance, NOT operational success. Forseti
    owns resume, adverse-effect recovery and durable holds. The ordinary outcome ledger
    needs its OWN independent workflow-outcome admission before a Process can advance.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        processes: ProcessRuntimeStore,
        reader: StateStoreAlertEffectReader,
        recovery_reader: StateStoreAlertEffectReader | None,
        outcomes: StateStoreWorkflowOutcomeLedger,
        publish: AlertEffectPublish | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._store, self._processes = store, processes
        self._reader, self._recovery = reader, recovery_reader
        self._outcomes, self._publish, self._clock = outcomes, publish, clock

    async def handle(self, payload: Mapping[str, Any]) -> bool:
        """Read retained Actions; audit untrusted, missing or reordered context as held."""
        notice: AlertExecutionNotice | None = None
        try:
            async with asyncio.timeout(40):
                # Producer identity must be supplied by the authenticated bus, never an HTTP caller.
                notice = AlertExecutionNotice.model_validate(
                    {key: payload.get(key) for key in AlertExecutionNotice.model_fields}
                )
                execution = await read_alert_execution(self._store, notice.action_digest)
                if execution is None or execution.source_event != notice:
                    raise AlertExecutionHeld("alert_effect_trigger_not_retained")
                if self._publish is None:
                    raise AlertExecutionHeld("alert_effect_owned_publisher_missing")
                reader = (
                    self._recovery
                    if execution.action.action_type == RESTORE_ACTION
                    else self._reader
                )
                if reader is None:
                    raise AlertExecutionHeld("alert_effect_recovery_reader_missing")
                result = await reader.read_admitted(
                    execution.plan, dispatch_ref=execution.dispatch_ref
                )
                if result is None:
                    raise AlertExecutionHeld("alert_effect_independent_observation_missing")
                if result.context.execution != execution:
                    raise AlertExecutionHeld("alert_effect_trigger_action_mismatch")
                await self._journal(result)
                return True
        except asyncio.CancelledError:
            await self._held("alert_effect_cancelled", notice)
            raise
        except Exception as exc:
            reason = (
                str(exc)
                if isinstance(exc, AlertExecutionHeld)
                else "alert_effect_context_unavailable"
            )
            await self._held(reason, notice)
            return False

    async def handle_missing(self, *, action_digest: str) -> bool:
        """Journal unknown only after the actual retained dispatch's final deadline.

        Called only by the Heimdall callback. A real observation wins a final re-read;
        otherwise the first actual clock instant is retained for stable restart replay.
        No valid receipt or numeric zero is manufactured for missing/partial evidence.
        """
        execution = await read_alert_execution(self._store, action_digest)
        if execution is None or self._publish is None:
            return False
        reader = self._recovery if execution.action.action_type == RESTORE_ACTION else self._reader
        if reader is None:
            return False
        async with asyncio.timeout(40):
            context = await reader.read_context(action_digest=action_digest)
            if context is None or context.execution != execution:
                raise AlertExecutionHeld("alert_effect_context_changed")
            now = self._clock()
            if now < alert_effect_deadline(context):
                return False
            try:
                result = await reader.read_admitted(
                    execution.plan, dispatch_ref=execution.dispatch_ref
                )
            except AlertExecutionHeld:
                result = None
            if result is not None and result.context.execution != execution:
                raise AlertExecutionHeld("alert_effect_context_changed")
            if (
                result is not None
                and classify_alert_effect(context, result.observation, now=self._clock()) != "held"
            ):
                await self._journal(result)
                return True
            candidate = alert_missing_effect_journal(
                context, source_revision=reader.source_revision, recorded_at=self._clock()
            )
            identity = {
                key: candidate[key]
                for key in (
                    "execution_ref",
                    "source_revision",
                    "observation_deadline",
                    "safeguard_bundle_digest",
                    "publication_receipt_digest",
                )
            }
            slot = "alert-noise:missing-effect:" + content_digest(identity)
            await self._store.write_state_if_absent(slot, candidate)
            retained = await self._store.read_state(slot)
            if retained is None:
                raise AlertExecutionHeld("alert_effect_missing_journal_unavailable")
            at = _TIME.validate_python(retained.get("recorded_at"))
            journal = alert_missing_effect_journal(
                context, source_revision=reader.source_revision, recorded_at=at
            )
            if retained != journal or at > self._clock() or self._clock() < now:
                raise AlertExecutionHeld("alert_effect_missing_journal_conflict")
            current = await reader.read_context(action_digest=action_digest)
            if (
                current is None
                or current.execution != execution
                or current.dispatched_at != context.dispatched_at
                or current.safeguard_bundle_digest != context.safeguard_bundle_digest
            ):
                raise AlertExecutionHeld("alert_effect_context_changed")
            key = await self._retain_journal(context, journal)
            await self._emit(context, journal, key=key, recorded_at=at)
            return True

    async def _journal(self, result: AdmittedAlertEffect) -> None:
        context, observation, admitted = result.context, result.observation, result.record
        execution, action = context.execution, context.execution.action
        lineage = action.workflow_action
        if lineage is None or self._publish is None:
            raise AlertExecutionHeld("alert_effect_journal_binding_missing")
        await admitted.require_unchanged(self._store)
        now = self._clock()
        admitted.require_current(now=now)
        outcome = classify_alert_effect(context, observation, now=now)
        response = alert_response_outcome(
            context, observation, receipt_digest=admitted.receipt_digest, now=now
        )
        journal = alert_effect_journal(result, now=now)
        key = await self._retain_journal(context, journal)
        await admitted.require_unchanged(self._store)
        admitted.require_current(now=self._clock())
        workflow_ref: str | None = None
        if response is not None and outcome in {"verified", "recovered"}:
            workflow_ref = await self._outcomes.record(
                action=action,
                execution_outcome=execution.execution_outcome,
                execution_receipt_ref=execution.publication_receipt.pr_ref,
                safeguard_bundle_digest=context.safeguard_bundle_digest,
                response_outcome=response,
            )
        await self._emit(
            context,
            journal,
            key=key,
            recorded_at=observation.recorded_at,
            workflow_ref=workflow_ref,
            admitted=admitted,
        )

    async def _retain_journal(self, context: AlertEffectContext, journal: dict[str, Any]) -> str:
        key = "alert-noise:outcome:" + content_digest(journal)
        created = await self._store.write_state_with_audit_if_absent(
            key,
            journal,
            {
                "actor": "Heimdall",
                "action_kind": "alert_noise.effect.recorded",
                "record_ref": key,
                "correlation_id": context.execution.source_event.correlation_id,
                "effect_outcome": journal["effect_outcome"],
                "execution_authority": False,
            },
        )
        if not created and await self._store.read_state(key) != journal:
            raise AlertExecutionHeld("alert_effect_journal_conflict")
        return key

    async def _emit(
        self,
        context: AlertEffectContext,
        journal: dict[str, Any],
        *,
        key: str,
        recorded_at: datetime,
        workflow_ref: str | None = None,
        admitted: AdmittedAlertRecord | None = None,
    ) -> None:
        execution, action = context.execution, context.execution.action
        lineage = action.workflow_action
        if lineage is None or self._publish is None:
            raise AlertExecutionHeld("alert_effect_journal_binding_missing")
        # No status transition: this child attaches the independent memory reference only.
        suffix = "alert-effect:" + content_digest(journal)
        await self._processes.append_event(
            ProcessEvent(
                event_id=event_id(lineage.process_id, suffix),
                process_id=lineage.process_id,
                kind=ProcessEventKind.EVIDENCE_ATTACHED,
                idempotency_key=f"{lineage.process_id}:{suffix}",
                recorded_at=recorded_at,
                correlation_id=execution.source_event.correlation_id,
                causation_id=require_alert_dispatch_lineage(context).event_id,
                step_id=lineage.step_id,
                attempt=lineage.attempt,
                payload={
                    "actor_agent": "Heimdall",
                    "domain": "alert_noise",
                    "evidence_ref": key,
                    "independent_observation_ref": (journal["effect_ref"] if admitted else None),
                    "execution_authority": False,
                },
            )
        )
        signal = AlertEffectDrift(
            correlation_id=execution.source_event.correlation_id,
            idempotency_key=suffix,
            resource_id=action.target_resource_ref,
            process_id=lineage.process_id,
            step_id=lineage.step_id,
            action_digest=full_action_digest(action),
            plan_digest=digest_record(execution.plan),
            dispatch_ref=execution.dispatch_ref,
            outcome_ref=key,
            effect_outcome=journal["effect_outcome"],
            workflow_outcome_ref=workflow_ref,
            recorded_at=recorded_at,
        )
        if admitted is not None:
            await admitted.require_unchanged(self._store)
            admitted.require_current(now=self._clock())
        await self._publish("Heimdall", "object.drift", signal.model_dump(mode="json"))

    async def _held(self, reason: str, notice: AlertExecutionNotice | None) -> None:
        async with asyncio.timeout(5):
            await self._store.append_audit_entry(
                {
                    "actor": "Heimdall",
                    "action_kind": "alert_noise.effect.held",
                    "reason": reason,
                    "correlation_id": notice.correlation_id
                    if notice
                    else "alert-noise:effect:unbound",
                    "action_id": str(notice.action_id) if notice else None,
                    "action_digest": notice.action_digest if notice else None,
                    "recorded_at": self._clock().isoformat(),
                    "execution_authority": False,
                    "promotion_authority": False,
                    "process_completed": False,
                }
            )
