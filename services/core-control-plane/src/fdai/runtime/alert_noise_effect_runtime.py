"""Own authenticated effect callbacks and their existing adapters, clock, locks and cursor."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.ontology_query import content_digest

from fdai.agents import ENVELOPE_SCHEMA_VERSION
from fdai.core.detection.alert_noise.execution import RESTORE_ACTION, AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    AlertEffectContext,
    AlertEffectDrift,
    AlertExecutedActionRecord,
    AlertExecutionNotice,
    alert_effect_deadline,
    classify_alert_effect,
)
from fdai.core.detection.alert_noise.workflow import (
    AlertWorkflowCoordinator,
    AlertWorkflowResolution,
)
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.outcome_verification import StateStoreWorkflowOutcomeLedger
from fdai.delivery.alert_noise_effects import (
    AdmittedAlertEffect,
    AlertEffectPublish,
    HeimdallAlertEffectHandler,
    StateStoreAlertEffectReader,
    read_alert_execution,
)
from fdai.delivery.alert_noise_evidence import exact_alert_model
from fdai.runtime import (
    alert_noise_effect_evidence,
    alert_noise_effect_planning,
    alert_noise_effect_relay,
)
from fdai.runtime.alert_noise_effect_config import _ENV_KEYS
from fdai.shared.providers.process_runtime import ProcessRuntimeStore, ProcessStatus
from fdai.shared.providers.state_store import StateStore

_ENVELOPE = {"schema_version", "envelope_schema_version"}


def _envelope_valid(payload: Mapping[str, Any]) -> bool:
    return all(
        type(payload.get(key, ENVELOPE_SCHEMA_VERSION)) is int
        and payload.get(key, ENVELOPE_SCHEMA_VERSION) == ENVELOPE_SCHEMA_VERSION
        for key in _ENVELOPE
    )


class AlertEffectRuntime:
    """Mechanical composition with immutable evidence and a restart-safe paging cursor.

    No Process transition is implemented here. Only a matched positive outcome can call
    AlertWorkflowCoordinator.resume; adverse outcomes issue existing logical-target holds.
    """

    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        store: StateStore,
        processes: ProcessRuntimeStore,
        workflows: AlertWorkflowCoordinator,
        outcomes: StateStoreWorkflowOutcomeLedger,
        holds: StateStoreAutomationHoldLedger,
        readers: Mapping[
            tuple[str, str], tuple[StateStoreAlertEffectReader, StateStoreAlertEffectReader]
        ],
        handlers: Mapping[tuple[str, str], HeimdallAlertEffectHandler],
        bindings: Mapping[tuple[str, str], dict[str, Any]],
        source_revision: str,
        publish: AlertEffectPublish,
        clock: Callable[[], datetime],
    ) -> None:
        """Retain supplied adapters; the public factory owns startup configuration checks."""
        self._environment, self._configuration = (
            environment,
            {key: environment.get(key) for key in _ENV_KEYS},
        )
        self._store, self._processes, self._workflows = store, processes, workflows
        self._outcomes, self._holds, self._readers = outcomes, holds, readers
        self._handlers, self._bindings, self._revision = handlers, bindings, source_revision
        self._publish, self._clock, self._tick_lock = publish, clock, asyncio.Lock()
        self._last_clock: datetime | None = None
        if holds.resource_lock is None:
            raise ValueError("alert effect runtime requires the composed logical-target lock")
        self._lock = holds.resource_lock
        self._cursor_key = "alert-noise:effect-scan:" + content_digest(
            {
                "source_revision": source_revision,
                "bindings": [content_digest(bindings[key]) for key in sorted(bindings)],
            }
        )

    def _current(self) -> datetime:
        if any(self._environment.get(key) != value for key, value in self._configuration.items()):
            raise AlertExecutionHeld("alert_effect_configuration_changed")
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise AlertExecutionHeld("alert_effect_clock_invalid")
        if self._last_clock is not None and now < self._last_clock:
            raise AlertExecutionHeld("alert_effect_clock_regressed")
        self._last_clock = now
        return now

    async def _execution(
        self, digest: str
    ) -> tuple[AlertExecutedActionRecord, StateStoreAlertEffectReader]:
        execution = await read_alert_execution(self._store, digest)
        if execution is None:
            raise AlertExecutionHeld("alert_effect_execution_missing")
        plan = execution.plan
        key = (plan.tenant_ref, plan.scope_ref)
        if key not in self._readers:
            raise AlertExecutionHeld("alert_effect_scope_unbound")
        retained = await self._store.read_state("alert-noise:plan:" + digest_record(plan))
        if retained is None or exact_alert_model(AlertChangePlan, dict(retained)) != plan:
            raise AlertExecutionHeld("alert_effect_plan_changed")
        self._current()
        return execution, self._readers[key][int(execution.action.action_type == RESTORE_ACTION)]

    async def observe(self, payload: Mapping[str, Any]) -> bool:
        """Heimdall callback for authenticated Thor alert_noise_publication only.

        A signature or caller-supplied status is not authentication. The parent bus must
        overwrite producer_principal; only retained references and real readers are used.
        Missing/unfinished proof is quiet before its deadline, then explicitly unknown.
        """
        notice: AlertExecutionNotice | None = None
        try:
            async with asyncio.timeout(45):
                self._current()
                allowed = (
                    set(AlertExecutionNotice.model_fields)
                    | _ENVELOPE
                    | {"kind", "resource_id", "idempotency_key"}
                )
                if (
                    payload.get("kind") != "alert_noise_publication"
                    or payload.get("producer_principal") != "Thor"
                    or set(payload) - allowed
                    or not _envelope_valid(payload)
                    or re.fullmatch(
                        r"alert-noise-effect:sha256:[a-f0-9]{64}",
                        str(payload.get("idempotency_key")),
                    )
                    is None
                ):
                    raise AlertExecutionHeld("alert_effect_ingress_untrusted")
                notice = exact_alert_model(
                    AlertExecutionNotice,
                    {key: payload.get(key) for key in AlertExecutionNotice.model_fields},
                )
                execution, reader = await self._execution(notice.action_digest)
                if (
                    execution.source_event != notice
                    or payload.get("resource_id") != execution.action.target_resource_ref
                ):
                    raise AlertExecutionHeld("alert_effect_trigger_not_retained")
                context = await reader.read_context(action_digest=notice.action_digest)
                if context is None or context.execution != execution:
                    raise AlertExecutionHeld("alert_effect_context_changed")
                if self._settled(context):
                    return True
                handler = self._handlers[(execution.plan.tenant_ref, execution.plan.scope_ref)]
                try:
                    result = await reader.read_admitted(
                        execution.plan, dispatch_ref=execution.dispatch_ref
                    )
                except AlertExecutionHeld:
                    result = None
                now = self._current()
                if (
                    result is not None
                    and classify_alert_effect(context, result.observation, now=now) != "held"
                ):
                    return await handler.handle(payload)
                return (
                    await handler.handle_missing(action_digest=notice.action_digest)
                    if now >= alert_effect_deadline(context)
                    else False
                )
        except Exception as exc:
            await self._held(
                "observe",
                exc,
                action_digest=notice.action_digest if notice else None,
                correlation_id=notice.correlation_id if notice else None,
            )
            return False

    async def plan(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Forseti callback: re-read the exact Heimdall journal before resume or durable holds.

        A recovered observation never releases a hold. The richer recovery coordinator
        needs a real failed-compensation attempt, approval and watermarks; none are invented.
        """
        signal: AlertEffectDrift | None = None
        try:
            async with asyncio.timeout(60):
                self._current()
                if (
                    payload.get("producer_principal") != "Heimdall"
                    or not _envelope_valid(payload)
                    or set(payload) - set(AlertEffectDrift.model_fields) - _ENVELOPE
                ):
                    raise AlertExecutionHeld("alert_effect_ingress_untrusted")
                signal = exact_alert_model(
                    AlertEffectDrift,
                    {key: payload.get(key) for key in AlertEffectDrift.model_fields},
                )
                return await alert_noise_effect_planning._plan(self, signal)
        except Exception as exc:
            return await self._held(
                "plan",
                exc,
                action_digest=signal.action_digest if signal else None,
                correlation_id=signal.correlation_id if signal else None,
            )

    async def _resolve(
        self, signal: AlertEffectDrift
    ) -> tuple[
        AlertEffectContext, AlertWorkflowResolution, dict[str, Any], AdmittedAlertEffect | None
    ]:
        return await alert_noise_effect_evidence._resolve(self, signal)

    async def _positive(
        self, signal: AlertEffectDrift, context: AlertEffectContext, admitted: AdmittedAlertEffect
    ) -> None:
        await alert_noise_effect_evidence._positive(self, signal, context, admitted)

    async def _unchanged(
        self,
        signal: AlertEffectDrift,
        context: AlertEffectContext,
        resolution: AlertWorkflowResolution,
        journal: Mapping[str, Any],
    ) -> None:
        await alert_noise_effect_evidence._unchanged(self, signal, context, resolution, journal)

    async def _child(
        self,
        signal: AlertEffectDrift,
        context: AlertEffectContext,
        *,
        recovery_required: bool,
        hold_digests: list[str],
        process_status: ProcessStatus | None = None,
    ) -> None:
        await alert_noise_effect_evidence._child(
            self,
            signal,
            context,
            recovery_required=recovery_required,
            hold_digests=hold_digests,
            process_status=process_status,
        )

    async def tick(self) -> int:
        """Scan at most one 100-record page, retaining offset progress across restart.

        Only existing state/evidence stores and the owned bus are contacted, not source
        providers or admission services. Growth adjusts the next offset; an overshoot
        visits the tail before wrapping. After the final deadline, an accepted publication
        without Forseti's durable child is retried with the same identity. Publication is
        at-least-once, never exactly-once; a broker acknowledgement is not consumer progress.
        """
        return await alert_noise_effect_relay._tick(self)

    def _settled(self, context: AlertEffectContext) -> bool:
        """Retain historical canonical consumption without claiming fresh success."""
        return alert_noise_effect_relay._settled(self, context)

    async def _notice(self, execution: AlertExecutedActionRecord) -> int:
        return await alert_noise_effect_relay._notice(self, execution)

    def _notification_receipt(
        self, context: AlertEffectContext, raw: Mapping[str, Any] | None
    ) -> str | None:
        """A matching record is a wake-up cue ONLY; the Heimdall reader still admits it."""
        return alert_noise_effect_relay._notification_receipt(self, context, raw)

    async def _held(
        self,
        operation: str,
        error: Exception,
        *,
        action_digest: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Retain one content-free correlated denial per unchanged input/reason."""
        reason = (
            str(error)
            if isinstance(error, AlertExecutionHeld)
            else "alert_effect_runtime_unavailable"
        )
        record = {
            "operation": operation,
            "reason": reason,
            "action_digest": action_digest,
            "status": "held",
            "source_revision": self._revision,
            "correlation_id": correlation_id,
            "recovery_required": None,
            "execution_authority": False,
        }
        actor = (
            "Forseti" if operation == "plan" else "Heimdall" if operation == "observe" else "Thor"
        )
        async with asyncio.timeout(5):
            await self._store.write_state_with_audit_if_absent(
                "alert-noise:effect-runtime-held:" + content_digest(record),
                record,
                {"actor": actor, "action_kind": "alert_noise.effect_runtime.held", **record},
            )
        return record
