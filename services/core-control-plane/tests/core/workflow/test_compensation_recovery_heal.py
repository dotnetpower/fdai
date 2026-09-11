"""Crash and restart coverage for the production compensation resume caller.

A crash between the guarded automation-hold release and the Process transition
leaves the hold released while the Process and its Saga delivery are still
open. The ordinary held-recovery branch can no longer see that work, because
the hold is gone. These tests drive the real production caller,
``WorkflowCompensationCoordinator.resume``, and prove it repairs the Process
and the Saga delivery after an arbitrary delay instead of closing the Process
outside the recovery completion it was released under.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.compensation import WorkflowCompensationCoordinator
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryDispatchOutcome,
    RecoveryDispatchResult,
    RecoveryPreDispatchClaim,
    recovery_attempt_step_id,
)
from fdai.core.workflow.recovery_coordinator import (
    RecoveryCoordinatorConfig,
    WorkflowRecoveryCoordinator,
)
from fdai.core.workflow.recovery_effect_ingress import (
    RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
    RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION,
    RecoveryEffectObservationIngress,
)
from fdai.delivery.persistence.state_store_hil_registry import StateStoreHilApprovalRegistry
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider
from fdai.delivery.persistence.workflow_recovery import (
    StateStoreRecoveryApprovalJournal,
    StateStoreRecoveryAttemptResolver,
    StateStoreRecoveryEffectObservationJournal,
    StateStoreRecoveryEffectObserver,
    StateStoreRecoverySafeguardBundleReader,
    StateStoreRecoverySafeguardBundleRetention,
)
from fdai.delivery.workflow_recovery_observation_handler import (
    RecoveryEffectObservationHandler,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.hil_registry import HilApprovalDecision
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
_TARGET = "resource:example/rg/compensation-heal-1"
_PROCESS_ID = "process-compensation-heal-1"
_CORRELATION_ID = "correlation-compensation-heal-1"
_SOURCE_REVISION = "commit:" + "a" * 40
_EXECUTOR = "executor@example.com"
_REQUESTER = "fdai.core.workflow.recovery-requester"
_APPROVER = "approver@example.com"
_OBSERVER = "heimdall-observer@example.com"
_OBSERVER_PRINCIPAL = "Heimdall"
_PROVIDER = "provider@example.com"
_BUNDLE_DIGEST = "sha256:" + "c" * 64
_RECEIPT_DIGEST = "sha256:" + "d" * 64
_ADMISSION_DIGEST = "sha256:" + "e" * 64
_APPLIED_STEP = "apply_first"
_COMPENSATION_ACTION_TYPE = "workflow.recovery.reconcile"
_COMPENSATION_PARAMS: dict[str, object] = {"reason": "revert the partially applied change"}
_RECEIPT_REF = "compensation-receipt-1"


class _Admissions:
    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        return DecisionEvidenceAdmission(
            receipt_digest=_ADMISSION_DIGEST,
            verification_bundle_digest="sha256:" + "f" * 64,
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
            verified_at=_NOW - timedelta(minutes=1),
            valid_until=_NOW + timedelta(minutes=30),
        )


class _Dispatcher:
    def __init__(self) -> None:
        self.calls: list[RecoveryPreDispatchClaim] = []

    async def dispatch_recovery(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
        safeguard_bundle_digest: str,
        target_resource_id: str,
        params: dict[str, object],
        correlation_id: str,
    ) -> RecoveryDispatchResult:
        del safeguard_bundle_digest, target_resource_id, params, correlation_id
        self.calls.append(claim)
        return RecoveryDispatchResult.create(
            attempt_identity_digest=attempt.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.DISPATCHED,
            provider_receipt_digest=_RECEIPT_DIGEST,
            recorded_at=_NOW,
        )

    async def reconcile_recovery(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
    ) -> RecoveryDispatchResult | None:
        del attempt, claim
        return None


class _AcceptingOutcomeVerifier:
    """Score every compensation outcome as verified at the production seam."""

    async def verify(
        self,
        *,
        process_id: str,
        step_id: str,
        proposal_ref: str,
        outcome: str,
        receipt_ref: str,
    ) -> bool:
        del process_id, step_id, proposal_ref, outcome, receipt_ref
        return True


class _CrashingProcessStore(InMemoryProcessRuntimeStore):
    """Fail exactly one terminal transition to simulate a crash after release."""

    def __init__(self) -> None:
        super().__init__()
        self._armed = False

    def arm(self) -> None:
        self._armed = True

    async def transition(self, **kwargs: object):  # type: ignore[override]
        if self._armed:
            self._armed = False
            raise RuntimeError("simulated crash after hold release")
        return await super().transition(**kwargs)  # type: ignore[arg-type]


async def _persisted_attempt(store: InMemoryStateStore) -> RecoveryAttemptIdentity:
    """Read the exact attempt the production recovery path already persisted.

    Recomputing the identity here would let the test agree with itself instead
    of with the coordinator, so the durable record is the only source.
    """

    record = await store.find_state(
        "workflow:recovery-attempt:",
        field="process_id",
        value=_PROCESS_ID,
    )
    assert record is not None, "the recovery path never persisted an attempt"
    return RecoveryAttemptIdentity(
        process_id=str(record["process_id"]),
        failed_compensation_proposal_digest=str(record["failed_compensation_proposal_digest"]),
        hold_revision=int(record["hold_revision"]),
        recovery_action_type=str(record["recovery_action_type"]),
        recovery_payload_digest=str(record["recovery_payload_digest"]),
        target_digest=str(record["target_digest"]),
        source_revision=str(record["source_revision"]),
        attempt_number=int(record["attempt_number"]),
        identity_digest=str(record["attempt_identity_digest"]),
    )


async def _compensating_process(
    process_store: InMemoryProcessRuntimeStore,
) -> ProcessSnapshot:
    """Build the durable Process journal a dispatched compensation leaves."""

    snapshot, _ = await process_store.create(
        snapshot=ProcessSnapshot(
            process_id=_PROCESS_ID,
            workflow_ref="recovery-flow",
            workflow_version="1",
            status=ProcessStatus.COMPENSATING,
            current_step=f"compensate_{_APPLIED_STEP}",
            target_resource_id=_TARGET,
            started_at=_NOW - timedelta(hours=1),
            updated_at=_NOW - timedelta(minutes=30),
            correlation_id=_CORRELATION_ID,
        ),
        event=ProcessEvent(
            event_id="event-created",
            process_id=_PROCESS_ID,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key=f"{_PROCESS_ID}:created",
            recorded_at=_NOW - timedelta(hours=1),
            correlation_id=_CORRELATION_ID,
        ),
    )
    await process_store.append_event(
        ProcessEvent(
            event_id="event-compensation-started",
            process_id=_PROCESS_ID,
            kind=ProcessEventKind.COMPENSATION_STARTED,
            idempotency_key=f"{_PROCESS_ID}:compensation:{_APPLIED_STEP}:started",
            recorded_at=_NOW - timedelta(minutes=40),
            correlation_id=_CORRELATION_ID,
            step_id=f"compensate_{_APPLIED_STEP}",
            payload={
                "compensates_step_id": _APPLIED_STEP,
                "action_type": _COMPENSATION_ACTION_TYPE,
                "params": dict(_COMPENSATION_PARAMS),
                "original_safeguard_bundle_digest": _BUNDLE_DIGEST,
            },
        )
    )
    await process_store.append_event(
        ProcessEvent(
            event_id="event-compensation-dispatched",
            process_id=_PROCESS_ID,
            kind=ProcessEventKind.COMPENSATION_DISPATCHED,
            idempotency_key=f"{_PROCESS_ID}:compensation:{_APPLIED_STEP}:dispatched",
            recorded_at=_NOW - timedelta(minutes=35),
            correlation_id=_CORRELATION_ID,
            step_id=f"compensate_{_APPLIED_STEP}",
            payload={
                "compensates_step_id": _APPLIED_STEP,
                "action_type": _COMPENSATION_ACTION_TYPE,
                "proposal_ref": f"{_PROCESS_ID}:compensate_{_APPLIED_STEP}",
            },
        )
    )
    refreshed = await process_store.get(_PROCESS_ID)
    assert refreshed is not None
    return refreshed


def _failed_compensation_proposal_digest() -> str:
    """Mirror the digest the compensation coordinator binds to one failure."""

    canonical = json.dumps(
        {
            "domain": "workflow-failed-compensation-proposal",
            "process_id": _PROCESS_ID,
            "receipt_refs": [_RECEIPT_REF],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _evidence_digest(value: str) -> str:
    if value.startswith("sha256:") and len(value) == len("sha256:") + 64:
        return value
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _context() -> dict[str, str]:
    return {
        f"compensation.{_APPLIED_STEP}.status": "verified",
        f"compensation.{_APPLIED_STEP}.receipt_ref": _RECEIPT_REF,
        f"compensation.{_APPLIED_STEP}.safeguard_bundle_digest": _BUNDLE_DIGEST,
    }


def _recovery_coordinator(
    store: InMemoryStateStore,
    process_store: InMemoryProcessRuntimeStore,
    dispatcher: _Dispatcher,
) -> WorkflowRecoveryCoordinator:
    journal = StateStoreRecoveryApprovalJournal(
        approvals=StateStoreWorkflowApprovalProvider(store),
        requester_principal=_REQUESTER,
        clock=lambda: _NOW,
    )
    return WorkflowRecoveryCoordinator(
        process_store=process_store,
        audit_store=store,
        holds=StateStoreAutomationHoldLedger(store, clock=lambda: _NOW),
        config=RecoveryCoordinatorConfig(
            executor_identity=_EXECUTOR,
            source_revision=_SOURCE_REVISION,
        ),
        dispatcher=dispatcher,  # type: ignore[arg-type]
        effect_observer=StateStoreRecoveryEffectObserver(store),
        effect_observations=StateStoreRecoveryEffectObservationJournal(
            store=store,
            executor_identity=_EXECUTOR,
        ),
        approval_reader=journal,
        approval_requester=journal,
        admission_provider=_Admissions(),  # type: ignore[arg-type]
        bundle_reader=StateStoreRecoverySafeguardBundleReader(store),
        clock=lambda: _NOW,
    )


def _compensation(
    store: InMemoryStateStore,
    process_store: InMemoryProcessRuntimeStore,
    recovery: WorkflowRecoveryCoordinator,
) -> WorkflowCompensationCoordinator:
    return WorkflowCompensationCoordinator(
        process_store=process_store,
        audit_store=store,
        dispatcher=None,
        outcome_verifier=_AcceptingOutcomeVerifier(),  # type: ignore[arg-type]
        recovery_coordinator=recovery,
    )


async def _approve(store: InMemoryStateStore) -> None:
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    pending = await registry.list_pending(limit=10)
    assert pending, "the recovery approval request never reached the HIL queue"
    for item in pending:
        await registry.record_decision(
            idempotency_key=item.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid=_APPROVER,
            justification="recovery approved by a separate human",
        )


async def _retain_bundle(store: InMemoryStateStore, attempt: RecoveryAttemptIdentity) -> None:
    """Retain the finalized bundle through the production retention writer."""

    assert await StateStoreRecoverySafeguardBundleRetention(store).retain_finalized_bundle(
        attempt=attempt,
        target_resource_id=_TARGET,
        safeguard_bundle_digest=_BUNDLE_DIGEST,
        finalized_at=_NOW,
    )


async def _observe(store: InMemoryStateStore, attempt: RecoveryAttemptIdentity) -> bool:
    """Publish the independent observation through the production ingress."""

    handler = RecoveryEffectObservationHandler(
        ingress=RecoveryEffectObservationIngress(
            attempts=StateStoreRecoveryAttemptResolver(store),
            journal=StateStoreRecoveryEffectObservationJournal(
                store=store,
                executor_identity=_EXECUTOR,
            ),
            executor_identity=_EXECUTOR,
            authorized_principals=frozenset({_OBSERVER_PRINCIPAL}),
            clock=lambda: _NOW,
        )
    )
    payload: dict[str, Any] = {
        "event_type": RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
        "observation_schema_version": RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION,
        "producer_principal": _OBSERVER_PRINCIPAL,
        "process_id": _PROCESS_ID,
        "recovery_step_id": recovery_attempt_step_id(attempt),
        "attempt_identity_digest": attempt.identity_digest,
        "target_resource_id": _TARGET,
        "provider_receipt_digest": _RECEIPT_DIGEST,
        "observer_identity": _OBSERVER,
        "observer_authority_class": "authoritative_external",
        "provider_identity": _PROVIDER,
        "purpose_version": "1.0.0",
        "method_version": "1.0.0",
        "event_time": (_NOW - timedelta(minutes=3)).isoformat(),
        "recorded_time": (_NOW - timedelta(minutes=2)).isoformat(),
        "freshness_policy_seconds": 600,
        "completeness": True,
        "provenance": "azure-resource-graph",
        "conflict_status": "none",
        "synthetic": False,
        "evidence_digest": "sha256:" + "7" * 64,
        "expected_effect_digest": "sha256:" + "8" * 64,
        "approved_envelope_digest": "sha256:" + "9" * 64,
        "action_digest": "sha256:" + "3" * 64,
        "evidence_window_start": (_NOW - timedelta(minutes=4)).isoformat(),
        "evidence_window_end": (_NOW - timedelta(minutes=1)).isoformat(),
        "watermarks": [
            {
                "source_id": "azure-activity-log",
                "watermark": (_NOW - timedelta(minutes=1)).isoformat(),
                "final": True,
                "watermark_digest": "sha256:" + "4" * 64,
            }
        ],
        "forbidden_effect_observed": False,
        "envelope_contained": True,
        "success": True,
    }
    return await handler.handle(payload, _OBSERVER_PRINCIPAL)


async def _recover(
    recovery: WorkflowRecoveryCoordinator,
    snapshot: ProcessSnapshot,
):
    return await recovery.recover(
        snapshot=snapshot,
        failed_compensation_proposal_digest=_failed_compensation_proposal_digest(),
        recovery_action_type=_COMPENSATION_ACTION_TYPE,
        recovery_params=_COMPENSATION_PARAMS,
        compensation_receipt_digests=(_evidence_digest(_BUNDLE_DIGEST),),
    )


async def _crashed_after_release() -> tuple[
    InMemoryStateStore,
    _CrashingProcessStore,
    ProcessSnapshot,
    _Dispatcher,
]:
    """Leave a released hold whose Process transition never committed.

    Every step runs through the production recovery path: the approval request,
    the separate human decision, the provider dispatch, the retained bundle and
    the independent observation. The terminal Process transition then dies the
    way a crashed replica does, so the durable release exists while the Process
    and its Saga delivery are still open.
    """

    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    process_store = _CrashingProcessStore()
    snapshot = await _compensating_process(process_store)
    holds = StateStoreAutomationHoldLedger(store, clock=lambda: _NOW)
    await holds.issue(
        target_ref=_TARGET,
        process_id=_PROCESS_ID,
        reason="compensation_failed",
    )
    dispatcher = _Dispatcher()
    recovery = _recovery_coordinator(store, process_store, dispatcher)

    requested = await _recover(recovery, snapshot)
    assert requested.reason == "approval_missing"
    await _approve(store)
    dispatched = await _recover(recovery, snapshot)
    assert dispatched.reason == "safeguard_denied"
    attempt = await _persisted_attempt(store)
    await _retain_bundle(store, attempt)
    assert await _observe(store, attempt)

    process_store.arm()
    with pytest.raises(RuntimeError, match="simulated crash"):
        await _recover(recovery, snapshot)
    return store, process_store, snapshot, dispatcher


class TestCompensationResumeHealsAReleasedRecovery:
    async def test_a_restart_repairs_the_process_and_the_saga_delivery(self) -> None:
        store, process_store, snapshot, dispatcher = await _crashed_after_release()

        assert not await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)
        crashed_events = await process_store.events(_PROCESS_ID)
        assert all(
            event.kind is not ProcessEventKind.RECOVERY_COMPLETED for event in crashed_events
        )

        restarted = _compensation(
            store,
            process_store,
            _recovery_coordinator(store, process_store, dispatcher),
        )
        result = await restarted.resume(
            snapshot=snapshot,
            target_resource_id=_TARGET,
            context=_context(),
        )

        assert result.recovery_incomplete is False
        assert result.snapshot.status is ProcessStatus.COMPENSATED
        healed_events = await process_store.events(_PROCESS_ID)
        assert healed_events[-1].kind is ProcessEventKind.RECOVERY_COMPLETED
        assert len(dispatcher.calls) == 1
        assert any(
            row["entry"].get("action_kind") == "workflow.compensation.recovery_healed"
            for row in store.audit_entries
        )
        assert any(
            row["entry"].get("action_kind") == "workflow.recovery.completed"
            for row in store.audit_entries
        )
        delivered = {
            row["entry"].get("delivery_kind")
            for row in store.audit_entries
            if row["entry"].get("action_kind") == "workflow.recovery.outbox_delivered"
        }
        assert delivered == {"process_event", "saga_audit"}

    async def test_a_second_restart_after_an_arbitrary_delay_stays_idempotent(self) -> None:
        store, process_store, snapshot, dispatcher = await _crashed_after_release()
        restarted = _compensation(
            store,
            process_store,
            _recovery_coordinator(store, process_store, dispatcher),
        )
        first = await restarted.resume(
            snapshot=snapshot,
            target_resource_id=_TARGET,
            context=_context(),
        )

        later = await restarted.resume(
            snapshot=first.snapshot,
            target_resource_id=_TARGET,
            context=_context(),
        )

        assert later.recovery_incomplete is False
        assert later.snapshot.status is ProcessStatus.COMPENSATED
        terminal_events = [
            event
            for event in await process_store.events(_PROCESS_ID)
            if event.kind is ProcessEventKind.RECOVERY_COMPLETED
        ]
        assert len(terminal_events) == 1
        assert len(dispatcher.calls) == 1

    async def test_nothing_to_repair_leaves_an_ordinary_resume_untouched(self) -> None:
        store = InMemoryStateStore(linearization_clock=lambda: _NOW)
        process_store = InMemoryProcessRuntimeStore()
        snapshot = await _compensating_process(process_store)
        compensation = _compensation(
            store,
            process_store,
            _recovery_coordinator(store, process_store, _Dispatcher()),
        )

        result = await compensation.resume(
            snapshot=snapshot,
            target_resource_id=_TARGET,
            context=_context(),
        )

        assert result.recovery_incomplete is False
        assert result.snapshot.status is ProcessStatus.COMPENSATED
        assert not any(
            row["entry"].get("action_kind") == "workflow.compensation.recovery_healed"
            for row in store.audit_entries
        )
