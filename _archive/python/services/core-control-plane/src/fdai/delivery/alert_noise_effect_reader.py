"""Read independently admitted effects against actual dispatch, closure and Process stores."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_base import AlertTime
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertEffectObservation
from fdai_service_contracts.decision_evidence import DecisionCriticalEvidenceReceipt
from fdai_service_contracts.ontology_query import content_digest
from pydantic import TypeAdapter

from fdai.core.detection.alert_noise.execution import RESTORE_ACTION, AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    ALERT_EFFECT_PURPOSE,
    ALERT_RECOVERY_EFFECT_PURPOSE,
    AlertEffectContext,
    AlertEffectPurpose,
    AlertExecutedActionRecord,
    alert_effect_deadline,
    alert_effect_key,
    require_alert_dispatch_lineage,
)
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureIdentity,
    PostReleaseClosureOutcome,
)
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_store import SafeguardDispatchEvidenceStore
from fdai.core.executor.safeguards import full_action_digest
from fdai.delivery.alert_noise_effect_records import AdmittedAlertEffect, read_alert_execution
from fdai.delivery.alert_noise_evidence import (
    alert_scope_digest,
    exact_alert_model,
    read_admitted_alert_record,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.process_runtime import ProcessRuntimeStore
from fdai.shared.providers.resource_lock import resource_lock_target_digest
from fdai.shared.providers.state_store import StateStore

_REF = re.compile(r"[a-z][a-z0-9_.:-]{0,159}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}")
_TIME: TypeAdapter[datetime] = TypeAdapter(AlertTime)


class StateStoreAlertEffectReader:
    """Implement AlertEffectReader using existing independently admitted private records.

    Key is alert_effect_key(plan_digest=digest_record(plan), dispatch_ref=proposal_ref).
    Exact payload: {observation, action_digest, dispatch_ref, dispatched_at,
    safeguard_bundle_digest}. The outer {payload, receipt} belongs to a real independent
    producer. A missing record/admission returns None; malformed or unavailable context raises
    a content-free hold. No observed boolean is inferred from publication or empty history.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        admissions: DecisionEvidenceAdmissionProvider | None,
        dispatches: SafeguardDispatchEvidenceStore,
        closures: PostReleaseClosureStore,
        processes: ProcessRuntimeStore,
        tenant_ref: str,
        scope_ref: str,
        source_revision: str,
        source_ref: str,
        observer_ref: str,
        executor_ref: str,
        identities: Mapping[str, str],
        authority_class: str,
        clock: Callable[[], datetime],
        purpose: AlertEffectPurpose = ALERT_EFFECT_PURPOSE,
    ) -> None:
        """Pin scope/version and three genuinely distinct identities, not just three aliases."""
        self._scope = alert_scope_digest(tenant_ref=tenant_ref, scope_ref=scope_ref)
        refs = (source_ref, observer_ref, executor_ref)
        mapped = tuple(identities.get(ref, "") for ref in refs)
        if (
            len(set(refs)) != 3
            or any(type(ref) is not str or _REF.fullmatch(ref) is None for ref in refs)
            or any(type(value) is not str or _IDENTITY.fullmatch(value) is None for value in mapped)
            or len({value.casefold() for value in mapped}) != 3
            or _IDENTITY.fullmatch(source_revision) is None
            or re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", authority_class) is None
            or purpose not in {ALERT_EFFECT_PURPOSE, ALERT_RECOVERY_EFFECT_PURPOSE}
        ):
            raise ValueError(
                "alert effect reader requires independent identity and source bindings"
            )
        self._store, self._admissions, self._dispatches = store, admissions, dispatches
        self._closures, self._processes = closures, processes
        self._revision, self._refs, self._source_identity = source_revision, refs, mapped[0]
        self._authority_class, self._clock, self._purpose = authority_class, clock, purpose

    @property
    def source_revision(self) -> str:
        """Return the configured revision also required of the actual safeguard record."""
        return self._revision

    async def read_context(self, *, action_digest: str) -> AlertEffectContext | None:
        """Resolve actual dispatch/closure timing even when no independent effect exists.

        This reads the real stores, never a private copy of their SQL records. It grants
        no success or recovery authority and does not require forward evidence to be fresh.
        """
        try:
            async with asyncio.timeout(25):
                execution = await read_alert_execution(self._store, action_digest)
                if execution is None:
                    return None
                action, plan = execution.action, execution.plan
                lineage = action.workflow_action
                purpose: AlertEffectPurpose = (
                    ALERT_RECOVERY_EFFECT_PURPOSE
                    if action.action_type == RESTORE_ACTION
                    else ALERT_EFFECT_PURPOSE
                )
                if (
                    alert_scope_digest(tenant_ref=plan.tenant_ref, scope_ref=plan.scope_ref)
                    != self._scope
                    or action.executor_identity_ref != self._refs[2]
                    or purpose != self._purpose
                    or lineage is None
                ):
                    raise AlertExecutionHeld("alert_effect_binding_mismatch")
                proof = await self._dispatch(execution)
                start = proof.dispatch_start_checkpoint
                snapshot = await self._processes.get(lineage.process_id)
                if (
                    start is None
                    or snapshot is None
                    or snapshot.target_resource_id != action.target_resource_ref
                    or snapshot.correlation_id != execution.source_event.correlation_id
                ):
                    raise AlertExecutionHeld("alert_effect_process_mismatch")
                context = AlertEffectContext(
                    execution,
                    start.dispatch_started_at,
                    proof.bundle.bundle_digest,
                    purpose,
                    await self._processes.events(lineage.process_id),
                )
                require_alert_dispatch_lineage(context)
                if (
                    await read_alert_execution(self._store, action_digest) != execution
                    or await self._dispatch(execution) != proof
                    or await self._processes.get(lineage.process_id) != snapshot
                ):
                    raise AlertExecutionHeld("alert_effect_context_changed")
                now = self._clock()
                if (
                    now.tzinfo is None
                    or now.utcoffset() is None
                    or not plan.created_at
                    <= action.created_at
                    <= context.dispatched_at
                    <= execution.source_event.terminal_at
                    <= now
                ):
                    raise AlertExecutionHeld("alert_effect_clock_invalid")
                return context
        except AlertExecutionHeld:
            raise
        except Exception:
            raise AlertExecutionHeld("alert_effect_context_unavailable") from None

    async def observe(
        self,
        plan: AlertChangePlan,
        *,
        dispatch_ref: str,
    ) -> AlertEffectObservation | None:
        """Return only the recorded observation, not a provider-success-derived substitute."""
        result = await self.read_admitted(plan, dispatch_ref=dispatch_ref)
        return None if result is None else result.observation

    async def read_admitted(
        self,
        plan: AlertChangePlan,
        *,
        dispatch_ref: str,
    ) -> AdmittedAlertEffect | None:
        """Retain the shared admission and dispatch lineage for the journal's final recheck."""
        try:
            async with asyncio.timeout(25):
                return await self._read(plan, dispatch_ref)
        except AlertExecutionHeld:
            raise
        except Exception:
            raise AlertExecutionHeld("alert_effect_read_unavailable") from None

    async def _read(self, plan: AlertChangePlan, dispatch_ref: str) -> AdmittedAlertEffect | None:
        now = self._clock()
        plan = AlertChangePlan.model_validate(plan)
        if alert_scope_digest(tenant_ref=plan.tenant_ref, scope_ref=plan.scope_ref) != self._scope:
            raise AlertExecutionHeld("alert_effect_scope_mismatch")
        key = alert_effect_key(plan_digest=digest_record(plan), dispatch_ref=dispatch_ref)
        record = await read_admitted_alert_record(
            self._store, self._admissions, key, self._purpose, self._scope, self._revision, now
        )
        if record is None:
            return None
        payload = record.payload
        if set(payload) != {
            "observation",
            "action_digest",
            "dispatch_ref",
            "dispatched_at",
            "safeguard_bundle_digest",
        }:
            raise AlertExecutionHeld("alert_effect_payload_invalid")
        observation = exact_alert_model(AlertEffectObservation, payload["observation"])
        execution = await read_alert_execution(self._store, payload["action_digest"])
        if execution is None:
            raise AlertExecutionHeld("alert_effect_retained_action_missing")
        if (
            execution.plan != plan
            or execution.dispatch_ref != dispatch_ref
            or observation.plan_digest != digest_record(plan)
            or payload["dispatch_ref"] != dispatch_ref
            or observation.dispatch_ref != dispatch_ref
            or (observation.source_ref, observation.observer_ref, observation.executor_ref)
            != self._refs
            or execution.action.executor_identity_ref != self._refs[2]
            or observation.synthetic
            or observation.coverage != "complete"
            or observation.recovery is not (self._purpose == ALERT_RECOVERY_EFFECT_PURPOSE)
        ):
            raise AlertExecutionHeld("alert_effect_binding_mismatch")
        proof = await self._dispatch(execution, payload["safeguard_bundle_digest"])
        start = proof.dispatch_start_checkpoint
        lineage = execution.action.workflow_action
        if start is None or lineage is None:
            raise AlertExecutionHeld("alert_effect_dispatch_missing")
        if _TIME.validate_python(payload["dispatched_at"]) != start.dispatch_started_at:
            raise AlertExecutionHeld("alert_effect_dispatch_time_mismatch")
        snapshot = await self._processes.get(lineage.process_id)
        if (
            snapshot is None
            or snapshot.target_resource_id != execution.action.target_resource_ref
            or snapshot.correlation_id != execution.source_event.correlation_id
        ):
            raise AlertExecutionHeld("alert_effect_process_mismatch")
        context = AlertEffectContext(
            execution,
            start.dispatch_started_at,
            proof.bundle.bundle_digest,
            self._purpose,
            await self._processes.events(lineage.process_id),
        )
        require_alert_dispatch_lineage(context)
        raw = await self._store.read_state(key)
        if raw is None or not record.matches(raw):
            raise AlertExecutionHeld("alert_effect_record_changed")
        receipt = exact_alert_model(DecisionCriticalEvidenceReceipt, raw["receipt"])
        if (
            receipt.source_identity != self._source_identity
            or receipt.authority_class != self._authority_class
            or not execution.source_event.terminal_at <= observation.window_start
            or not context.dispatched_at <= receipt.event_at <= observation.window_end
            or not observation.window_end
            <= receipt.evidence_cutoff
            <= alert_effect_deadline(context)
            or not observation.recorded_at <= receipt.recorded_at <= record.admission.verified_at
        ):
            raise AlertExecutionHeld("alert_effect_source_or_cutoff_mismatch")
        if await read_alert_execution(self._store, payload["action_digest"]) != execution:
            raise AlertExecutionHeld("alert_effect_execution_changed")
        if await self._dispatch(execution, payload["safeguard_bundle_digest"]) != proof:
            raise AlertExecutionHeld("alert_effect_dispatch_changed")
        await record.require_unchanged(self._store)
        at = self._clock()
        if at < now:
            raise AlertExecutionHeld("alert_effect_clock_regressed")
        record.require_current(now=at)
        return AdmittedAlertEffect(context, observation, record, key)

    async def _dispatch(
        self,
        execution: AlertExecutedActionRecord,
        bundle_digest: str | None = None,
    ) -> SafeguardDispatchEvidenceRecord:
        action = execution.action
        proof = await self._dispatches.read(
            resource_lock_target_digest(action.target_resource_ref), execution.dispatch_generation
        )
        if type(proof) is not SafeguardDispatchEvidenceRecord:
            raise AlertExecutionHeld("alert_effect_dispatch_evidence_missing")
        proof = replace(proof)
        start, observed = proof.dispatch_start_checkpoint, proof.dispatch_observation
        identity = proof.identity
        if (
            proof.state is not SafeguardDispatchEvidenceState.PRE_RELEASE
            or start is None
            or observed is None
            or identity.action_id != str(action.action_id)
            or identity.target_digest != resource_lock_target_digest(action.target_resource_ref)
            or identity.target_fence_generation != execution.dispatch_generation
            or identity.source_revision != self._revision
            or identity.execution_path != "pr_manual"
            or identity.sink_idempotency_key != action.idempotency_key
            or (bundle_digest is not None and proof.bundle.bundle_digest != bundle_digest)
            or start.in_flight_reservation_receipt.record.identity.action_digest
            != full_action_digest(action)
            or observed.sink_state is not AuthoritativeSinkState.COMMITTED
            or observed.transport_state is not DispatchTransportState.ACKNOWLEDGED
            or proof.state_changed_at > execution.source_event.terminal_at
        ):
            raise AlertExecutionHeld("alert_effect_dispatch_evidence_mismatch")
        publication = execution.publication_receipt
        if observed.sink_operation_reference_digest != content_digest(
            {"domain": "pr-publish-reference", "pr_ref": publication.pr_ref}
        ) or observed.authoritative_status_digest != content_digest(
            {
                "domain": "pr-publish-status",
                "pr_ref": publication.pr_ref,
                "state": publication.state,
                "already_existed": publication.already_existed,
            }
        ):
            raise AlertExecutionHeld("alert_effect_publication_mismatch")
        closure_identity = PostReleaseClosureIdentity.from_pre_release(proof)
        closure = await self._closures.read_receipt(closure_identity.closure_key)
        if (
            closure is None
            or closure.record.identity != closure_identity
            or closure.record.outcome is not PostReleaseClosureOutcome.RESOLVED
            or closure.record.pre_release_record_digest != proof.record_digest
            or closure.record.pre_release_record_revision != proof.revision
            or closure.record.closed_at > execution.source_event.terminal_at
        ):
            raise AlertExecutionHeld("alert_effect_dispatch_closure_unavailable")
        return proof
