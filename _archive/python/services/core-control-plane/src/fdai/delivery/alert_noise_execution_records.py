"""Executor-owned immutable publication observations and a replayable reference outbox."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fdai_service_contracts.alert_noise_plan import AlertChangePlan

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    AlertExecutedActionRecord,
    AlertExecutionNotice,
    alert_executed_action_key,
)
from fdai.core.executor.safeguard_lifecycle_models import (
    SafeguardCoordinatedDispatchResult,
    SafeguardCoordinationDisposition,
)
from fdai.core.executor.safeguards import full_action_digest
from fdai.shared.contracts.models import Action
from fdai.shared.providers.process_runtime import ProcessRuntimeStore
from fdai.shared.providers.remediation_pr import PublishReceipt
from fdai.shared.providers.state_store import StateStore


class StateStoreAlertPublicationRecorder:
    """Retain the coordinator's actual generation and receipt, never inferred effect success."""

    def __init__(
        self, *, store: StateStore, processes: ProcessRuntimeStore, clock: Callable[[], datetime]
    ) -> None:
        self._store, self._processes, self._clock = store, processes, clock

    async def record(
        self,
        *,
        action: Action,
        plan: AlertChangePlan,
        receipt: PublishReceipt,
        result: SafeguardCoordinatedDispatchResult,
    ) -> None:
        """Journal the immutable original publication after authoritative post-release closure."""
        lifecycle, closure = result.lifecycle, result.closure_receipt
        lineage = action.workflow_action
        if (
            result.disposition is not SafeguardCoordinationDisposition.COMPLETED
            or not result.dispatch_performed
            or lifecycle is None
            or lifecycle.evidence_record is None
            or closure is None
            or lineage is None
        ):
            raise AlertExecutionHeld("alert_publication_closure_missing")
        proof = lifecycle.evidence_record
        snapshot = await self._processes.get(lineage.process_id)
        if snapshot is None or snapshot.target_resource_id != action.target_resource_ref:
            raise AlertExecutionHeld("alert_publication_process_missing")
        digest = full_action_digest(action)
        key = alert_executed_action_key(digest)
        prior = await self._store.read_state(key)
        if prior is not None:
            previous = AlertExecutedActionRecord.model_validate(prior)
            if (
                previous.action != action
                or previous.plan != plan
                or previous.publication_receipt != receipt
                or previous.dispatch_generation != proof.identity.target_fence_generation
            ):
                raise AlertExecutionHeld("alert_publication_record_conflict")
            return
        at = self._clock()
        if closure.record.closed_at > at or proof.identity.action_id != str(action.action_id):
            raise AlertExecutionHeld("alert_publication_closure_mismatch")
        notice = AlertExecutionNotice(
            producer_principal="Thor",
            action_id=action.action_id,
            action_digest=digest,
            correlation_id=snapshot.correlation_id,
            state="effect_observing",
            terminal_at=at,
        )
        record = AlertExecutedActionRecord(
            action=action,
            plan=plan,
            publication_receipt=receipt,
            execution_outcome="already_existed" if receipt.already_existed else "published",
            dispatch_generation=proof.identity.target_fence_generation,
            source_event=notice,
        )
        raw = record.model_dump(mode="json")
        created = await self._store.write_state_with_audit_if_absent(
            key,
            raw,
            {
                "actor": "Thor",
                "action_kind": "alert_noise.publication.recorded",
                "action_digest": digest,
                "correlation_id": snapshot.correlation_id,
                "safeguard_bundle_digest": result.bundle_digest,
                "effect_verified": False,
            },
        )
        if not created and await self._store.read_state(key) != raw:
            raise AlertExecutionHeld("alert_publication_record_conflict")
