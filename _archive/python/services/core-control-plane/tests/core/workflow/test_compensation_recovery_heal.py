"""Crash and restart coverage for the production compensation resume caller."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
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
    RecoveryCoordinationResult,
    RecoveryCoordinatorConfig,
    RecoveryDisposition,
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
        self, *, evidence_digest: str, scope_digest: str, purpose_id: str, source_revision: str
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
        **kwargs: object,
    ) -> RecoveryDispatchResult:
        del kwargs
        self.calls.append(claim)
        return RecoveryDispatchResult.create(
            attempt_identity_digest=attempt.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.DISPATCHED,
            provider_receipt_digest=_RECEIPT_DIGEST,
            recorded_at=_NOW,
        )

    async def reconcile_recovery(self, **kwargs: object) -> RecoveryDispatchResult | None:
        del kwargs
        return None


class _AcceptingOutcomeVerifier:
    async def verify(self, **kwargs: object) -> bool:
        del kwargs
        return True


class _CrashingProcessStore(InMemoryProcessRuntimeStore):
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
    record = await store.find_state(
        "workflow:recovery-attempt:", field="process_id", value=_PROCESS_ID
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


async def _compensating_process(process_store: InMemoryProcessRuntimeStore) -> ProcessSnapshot:
    await process_store.create(
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
    for eid, kind, suffix, payload in (
        (
            "event-compensation-started",
            ProcessEventKind.COMPENSATION_STARTED,
            "started",
            {
                "compensates_step_id": _APPLIED_STEP,
                "action_type": _COMPENSATION_ACTION_TYPE,
                "params": dict(_COMPENSATION_PARAMS),
                "original_safeguard_bundle_digest": _BUNDLE_DIGEST,
            },
        ),
        (
            "event-compensation-dispatched",
            ProcessEventKind.COMPENSATION_DISPATCHED,
            "dispatched",
            {
                "compensates_step_id": _APPLIED_STEP,
                "action_type": _COMPENSATION_ACTION_TYPE,
                "proposal_ref": f"{_PROCESS_ID}:compensate_{_APPLIED_STEP}",
            },
        ),
    ):
        await process_store.append_event(
            ProcessEvent(
                event_id=eid,
                process_id=_PROCESS_ID,
                kind=kind,
                idempotency_key=f"{_PROCESS_ID}:compensation:{_APPLIED_STEP}:{suffix}",
                recorded_at=_NOW - timedelta(minutes=35),
                correlation_id=_CORRELATION_ID,
                step_id=f"compensate_{_APPLIED_STEP}",
                payload=payload,
            )
        )
    refreshed = await process_store.get(_PROCESS_ID)
    assert refreshed is not None
    return refreshed


def _failed_compensation_proposal_digest() -> str:
    body = (
        '{"domain":"workflow-failed-compensation-proposal",'
        f'"process_id":"{_PROCESS_ID}","receipt_refs":["{_RECEIPT_REF}"]}}'
    )
    return f"sha256:{hashlib.sha256(body.encode()).hexdigest()}"


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
            executor_identity=_EXECUTOR, source_revision=_SOURCE_REVISION
        ),
        dispatcher=dispatcher,  # type: ignore[arg-type]
        effect_observer=StateStoreRecoveryEffectObserver(store),
        effect_observations=StateStoreRecoveryEffectObservationJournal(
            store=store, executor_identity=_EXECUTOR
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


async def _observe(store: InMemoryStateStore, attempt: RecoveryAttemptIdentity) -> bool:
    handler = RecoveryEffectObservationHandler(
        ingress=RecoveryEffectObservationIngress(
            attempts=StateStoreRecoveryAttemptResolver(store),
            journal=StateStoreRecoveryEffectObservationJournal(
                store=store, executor_identity=_EXECUTOR
            ),
            executor_identity=_EXECUTOR,
            authorized_principals=frozenset({_OBSERVER_PRINCIPAL}),
            trusted_observer_identities=frozenset({_OBSERVER}),
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


async def _recover(recovery: WorkflowRecoveryCoordinator, snapshot: ProcessSnapshot):
    return await recovery.recover(
        snapshot=snapshot,
        failed_compensation_proposal_digest=_failed_compensation_proposal_digest(),
        recovery_action_type=_COMPENSATION_ACTION_TYPE,
        recovery_params=_COMPENSATION_PARAMS,
        compensation_receipt_digests=(_BUNDLE_DIGEST,),
    )


async def _crashed_after_release() -> tuple[
    InMemoryStateStore, _CrashingProcessStore, ProcessSnapshot, _Dispatcher
]:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    process_store = _CrashingProcessStore()
    snapshot = await _compensating_process(process_store)
    holds = StateStoreAutomationHoldLedger(store, clock=lambda: _NOW)
    await holds.issue(target_ref=_TARGET, process_id=_PROCESS_ID, reason="compensation_failed")
    dispatcher = _Dispatcher()
    recovery = _recovery_coordinator(store, process_store, dispatcher)
    requested = await _recover(recovery, snapshot)
    assert requested.reason == "approval_missing"
    await _approve(store)
    dispatched = await _recover(recovery, snapshot)
    assert dispatched.reason == "safeguard_denied"
    attempt = await _persisted_attempt(store)
    assert await StateStoreRecoverySafeguardBundleRetention(store).retain_finalized_bundle(
        attempt=attempt,
        target_resource_id=_TARGET,
        safeguard_bundle_digest=_BUNDLE_DIGEST,
        finalized_at=_NOW,
    )
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
            store, process_store, _recovery_coordinator(store, process_store, dispatcher)
        )
        result = await restarted.resume(
            snapshot=snapshot, target_resource_id=_TARGET, context=_context()
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
            store, process_store, _recovery_coordinator(store, process_store, dispatcher)
        )
        first = await restarted.resume(
            snapshot=snapshot, target_resource_id=_TARGET, context=_context()
        )
        later = await restarted.resume(
            snapshot=first.snapshot, target_resource_id=_TARGET, context=_context()
        )
        assert later.recovery_incomplete is False
        assert later.snapshot.status is ProcessStatus.COMPENSATED
        terminal_events = [
            event
            for event in await process_store.events(_PROCESS_ID)
            if event.kind is ProcessEventKind.RECOVERY_COMPLETED
        ]
        assert len(terminal_events) == 1 and len(dispatcher.calls) == 1

    async def test_nothing_to_repair_leaves_an_ordinary_resume_untouched(self) -> None:
        store = InMemoryStateStore(linearization_clock=lambda: _NOW)
        process_store = InMemoryProcessRuntimeStore()
        snapshot = await _compensating_process(process_store)
        compensation = _compensation(
            store, process_store, _recovery_coordinator(store, process_store, _Dispatcher())
        )
        result = await compensation.resume(
            snapshot=snapshot, target_resource_id=_TARGET, context=_context()
        )
        assert result.recovery_incomplete is False
        assert result.snapshot.status is ProcessStatus.COMPENSATED
        assert not any(
            row["entry"].get("action_kind") == "workflow.compensation.recovery_healed"
            for row in store.audit_entries
        )


@dataclass(frozen=True)
class _StubActionDispatcher:
    ref: str = "prop-comp-1"
    fail: bool = False

    async def dispatch(self, **kwargs: object) -> str:
        del kwargs
        if self.fail:
            raise RuntimeError("dispatch failure")
        return self.ref


@dataclass(frozen=True)
class _StubOutcomeVerifier:
    accept: bool = True
    fail: bool = False

    async def verify(self, **kwargs: object) -> bool:
        del kwargs
        if self.fail:
            raise RuntimeError("verifier failure")
        return self.accept


@dataclass(frozen=True)
class _StubResolvedOutcome:
    outcome: str = "succeeded"
    receipt_ref: str = "r-1"
    safeguard_bundle_digest: str | None = _BUNDLE_DIGEST


@dataclass(frozen=True)
class _StubOutcomeResolver:
    resolved: _StubResolvedOutcome | None = None

    async def resolve(self, **kwargs: object) -> Any:
        del kwargs
        return self.resolved

    async def verify(self, **kwargs: object) -> bool:
        del kwargs
        return True


@dataclass(frozen=True)
class _StubRecoveryCoordinator:
    heal_result: RecoveryCoordinationResult | None = None
    heal_fail: bool = False
    recover_result: RecoveryCoordinationResult | None = None
    recover_fail: bool = False
    release_hold: StateStoreAutomationHoldLedger | None = None
    terminalize_store: InMemoryProcessRuntimeStore | None = None

    async def heal(self, *, snapshot: ProcessSnapshot) -> RecoveryCoordinationResult | None:
        del snapshot
        if self.heal_fail:
            raise RuntimeError("heal error")
        return self.heal_result

    async def recover(self, **kwargs: object) -> RecoveryCoordinationResult:
        snapshot: ProcessSnapshot = kwargs["snapshot"]  # type: ignore[assignment]
        if self.recover_fail:
            raise RuntimeError("recover error")
        if self.release_hold is not None:
            self.release_hold.store._state.clear()  # type: ignore[attr-defined]
        if self.terminalize_store is not None:
            await self.terminalize_store.transition(
                process_id=snapshot.process_id,
                expected_revision=snapshot.revision,
                status=ProcessStatus.COMPENSATED,
                current_step="",
                event=ProcessEvent(
                    event_id="ev-term",
                    process_id=snapshot.process_id,
                    kind=ProcessEventKind.RECOVERY_COMPLETED,
                    idempotency_key=f"{snapshot.process_id}:rec-done",
                    recorded_at=_NOW,
                    correlation_id=snapshot.correlation_id,
                ),
            )
        assert self.recover_result is not None
        return self.recover_result


async def _seed_applied_process(
    *, with_applied: bool = True, with_bundle: bool = True, with_dispatch_params: bool = True
) -> tuple[InMemoryStateStore, InMemoryProcessRuntimeStore, ProcessSnapshot]:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    pstore = InMemoryProcessRuntimeStore()
    snap, _ = await pstore.create(
        snapshot=ProcessSnapshot(
            process_id=_PROCESS_ID,
            workflow_ref="wf",
            workflow_version="1",
            status=ProcessStatus.RUNNING,
            current_step=_APPLIED_STEP,
            target_resource_id=_TARGET,
            started_at=_NOW,
            updated_at=_NOW,
            correlation_id=_CORRELATION_ID,
        ),
        event=ProcessEvent(
            event_id="e-0",
            process_id=_PROCESS_ID,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="e-0",
            recorded_at=_NOW,
            correlation_id=_CORRELATION_ID,
        ),
    )
    if with_applied:
        for eid, kind, payload in (
            (
                "e-disp",
                ProcessEventKind.ACTION_DISPATCHED,
                {"params": {"k": "v"} if with_dispatch_params else "bad"},
            ),
            (
                "e-done",
                ProcessEventKind.STEP_COMPLETED,
                {
                    "reason": "action_effect_verified",
                    **({"safeguard_bundle_digest": _BUNDLE_DIGEST} if with_bundle else {}),
                },
            ),
        ):
            await pstore.append_event(
                ProcessEvent(
                    event_id=eid,
                    process_id=_PROCESS_ID,
                    kind=kind,
                    idempotency_key=eid,
                    recorded_at=_NOW,
                    correlation_id=_CORRELATION_ID,
                    step_id=_APPLIED_STEP,
                    payload=payload,
                )
            )
    return store, pstore, snap


class TestWorkflowCompensationStartAndResume:
    async def test_start_branches(self) -> None:
        store, pstore, snap = await _seed_applied_process(with_applied=False)
        coord = WorkflowCompensationCoordinator(
            process_store=pstore, audit_store=store, dispatcher=None, outcome_verifier=None
        )
        assert (
            await coord.start(
                snapshot=snap, compensations={}, target_resource_id=_TARGET, context={}
            )
            is None
        )
        for with_bundle, with_params, comp_map, dispatcher, exp_inc in (
            (True, True, {}, _StubActionDispatcher(), True),
            (False, True, {_APPLIED_STEP: "ops.comp"}, _StubActionDispatcher(), True),
            (True, False, {_APPLIED_STEP: "ops.comp"}, _StubActionDispatcher(), True),
            (True, True, {_APPLIED_STEP: "ops.comp"}, None, True),
            (True, True, {_APPLIED_STEP: "ops.comp"}, _StubActionDispatcher(fail=True), True),
            (True, True, {_APPLIED_STEP: "ops.comp"}, _StubActionDispatcher(ref="   "), True),
            (True, True, {_APPLIED_STEP: "ops.comp"}, _StubActionDispatcher(ref="prop-1"), False),
        ):
            s, ps, sn = await _seed_applied_process(
                with_bundle=with_bundle, with_dispatch_params=with_params
            )
            c = WorkflowCompensationCoordinator(
                process_store=ps, audit_store=s, dispatcher=dispatcher, outcome_verifier=None
            )
            res = await c.start(
                snapshot=sn, compensations=comp_map, target_resource_id=_TARGET, context={}
            )
            assert res is not None and res.recovery_incomplete is exp_inc

    async def test_resume_intent_and_verifier_branches(self) -> None:
        valid_intent = {
            "compensates_step_id": _APPLIED_STEP,
            "action_type": "ops.comp",
            "params": {"k": "v"},
        }
        for disp, intent_payload in (
            (None, None),
            (None, {"compensates_step_id": "", "action_type": "", "params": None}),
            (None, valid_intent),
            (_StubActionDispatcher(ref="prop-late"), valid_intent),
        ):
            s1, ps1, sn1 = await _seed_applied_process(with_applied=False)
            if intent_payload is not None:
                await ps1.append_event(
                    ProcessEvent(
                        event_id="e-int",
                        process_id=_PROCESS_ID,
                        kind=ProcessEventKind.COMPENSATION_STARTED,
                        idempotency_key="e-int",
                        recorded_at=_NOW,
                        correlation_id=_CORRELATION_ID,
                        payload=intent_payload,
                    )
                )
            c1 = WorkflowCompensationCoordinator(
                process_store=ps1, audit_store=s1, dispatcher=disp, outcome_verifier=None
            )
            assert (
                await c1.resume(snapshot=sn1, target_resource_id=_TARGET, context={})
            ).recovery_incomplete is True

        for ctx, verifier, exp_inc in (
            ({}, _StubOutcomeVerifier(), False),
            ({}, _StubOutcomeResolver(None), False),
            ({f"compensation.{_APPLIED_STEP}.status": "invalid"}, _StubOutcomeVerifier(), True),
            ({f"compensation.{_APPLIED_STEP}.status": "verified"}, _StubOutcomeVerifier(), True),
            (_context(), _StubOutcomeVerifier(accept=False), True),
            (_context(), _StubOutcomeVerifier(fail=True), True),
            (
                {
                    f"compensation.{_APPLIED_STEP}.status": "failed",
                    f"compensation.{_APPLIED_STEP}.receipt_ref": "r-fail",
                },
                _StubOutcomeVerifier(accept=True),
                True,
            ),
            ({}, _StubOutcomeResolver(_StubResolvedOutcome(outcome="not_attempted")), True),
            (
                {},
                _StubOutcomeResolver(
                    _StubResolvedOutcome(outcome="succeeded", safeguard_bundle_digest=None)
                ),
                True,
            ),
        ):
            ps_i = InMemoryProcessRuntimeStore()
            sn_i = await _compensating_process(ps_i)
            c_i = WorkflowCompensationCoordinator(
                process_store=ps_i,
                audit_store=InMemoryStateStore(linearization_clock=lambda: _NOW),
                dispatcher=None,
                outcome_verifier=verifier,  # type: ignore[arg-type]
            )
            assert (
                await c_i.resume(snapshot=sn_i, target_resource_id=_TARGET, context=ctx)
            ).recovery_incomplete is exp_inc

    async def test_heal_and_hold_recovery_branches(self) -> None:
        unverified = RecoveryCoordinationResult(
            disposition=RecoveryDisposition.EFFECT_UNVERIFIED, reason="unverified"
        )
        completed = RecoveryCoordinationResult(disposition=RecoveryDisposition.COMPLETED)
        for heal_fail, heal_res, exp_inc in (
            (True, None, True),
            (False, unverified, True),
            (False, completed, False),
        ):
            ps_h = InMemoryProcessRuntimeStore()
            sn_h = await _compensating_process(ps_h)
            c_h = WorkflowCompensationCoordinator(
                process_store=ps_h,
                audit_store=InMemoryStateStore(linearization_clock=lambda: _NOW),
                dispatcher=None,
                outcome_verifier=_AcceptingOutcomeVerifier(),
                recovery_coordinator=_StubRecoveryCoordinator(  # type: ignore[arg-type]
                    heal_fail=heal_fail, heal_result=heal_res
                ),
            )
            assert (
                await c_h.resume(snapshot=sn_h, target_resource_id=_TARGET, context=_context())
            ).recovery_incomplete is exp_inc

        denied = RecoveryCoordinationResult(disposition=RecoveryDisposition.REJECTED, reason="no")
        plain = _StubOutcomeResolver(
            _StubResolvedOutcome(safeguard_bundle_digest="plain-bundle-ref")
        )
        for rec_coord in (
            None,
            _StubRecoveryCoordinator(recover_fail=True),
            _StubRecoveryCoordinator(recover_result=denied),
        ):
            s_r = InMemoryStateStore(linearization_clock=lambda: _NOW)
            ps_r = InMemoryProcessRuntimeStore()
            sn_r = await _compensating_process(ps_r)
            await StateStoreAutomationHoldLedger(s_r, clock=lambda: _NOW).issue(
                target_ref=_TARGET, process_id=_PROCESS_ID, reason="held"
            )
            c_r = WorkflowCompensationCoordinator(
                process_store=ps_r,
                audit_store=s_r,
                dispatcher=None,
                outcome_verifier=plain,  # type: ignore[arg-type]
                recovery_coordinator=rec_coord,  # type: ignore[arg-type]
            )
            assert (
                await c_r.resume(snapshot=sn_r, target_resource_id=_TARGET, context={})
            ).recovery_incomplete is True

        for term_in_recover, disp in (
            (True, RecoveryDisposition.COMPLETED),
            (False, RecoveryDisposition.COMPLETED),
            (True, RecoveryDisposition.NOT_REQUIRED),
        ):
            s_ok = InMemoryStateStore(linearization_clock=lambda: _NOW)
            ps_ok = InMemoryProcessRuntimeStore()
            sn_ok = await _compensating_process(ps_ok)
            holds = StateStoreAutomationHoldLedger(s_ok, clock=lambda: _NOW)
            await holds.issue(target_ref=_TARGET, process_id=_PROCESS_ID, reason="held")
            rec = _StubRecoveryCoordinator(
                recover_result=RecoveryCoordinationResult(disposition=disp),
                release_hold=holds,
                terminalize_store=ps_ok if term_in_recover else None,
            )
            c_ok = WorkflowCompensationCoordinator(
                process_store=ps_ok,
                audit_store=s_ok,
                dispatcher=None,
                outcome_verifier=_AcceptingOutcomeVerifier(),
                recovery_coordinator=rec,  # type: ignore[arg-type]
                automation_holds=holds,
            )
            res_ok = await c_ok.resume(
                snapshot=sn_ok, target_resource_id=_TARGET, context=_context()
            )
            assert not res_ok.recovery_incomplete
            assert res_ok.snapshot.status is ProcessStatus.COMPENSATED
