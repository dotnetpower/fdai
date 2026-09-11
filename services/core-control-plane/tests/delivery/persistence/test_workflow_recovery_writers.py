"""Production call-site coverage for every workflow recovery evidence writer.

The recovery coordinator only reads durable evidence, so each record it needs
must have a real production writer: the approval request goes through the
existing workflow approval journal, the finalized safeguard bundle is retained
from the production dispatch outcome, and the independent post-effect
observation is persisted through the explicit observer journal. This module
proves the path completes with no test-only seeded recovery state, and that a
missing writer stays a visible fail-closed state.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

import pytest
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryDispatchOutcome,
    RecoveryDispatchResult,
    RecoveryPreDispatchClaim,
    recovery_attempt_step_id,
)
from fdai.core.workflow.recovery_coordinator import (
    RecoveryCoordinatorConfig,
    RecoveryDisposition,
    RecoveryEffectObservation,
    WorkflowRecoveryCoordinator,
)
from fdai.core.workflow.recovery_effect_claim import (
    EffectEvidenceClass,
    EffectEvidenceRecord,
    FinalizedWatermark,
)
from fdai.delivery.persistence.state_store_hil_registry import StateStoreHilApprovalRegistry
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider
from fdai.delivery.persistence.workflow_recovery import (
    StateStoreRecoveryApprovalJournal,
    StateStoreRecoveryEffectObservationJournal,
    StateStoreRecoveryEffectObserver,
    StateStoreRecoverySafeguardBundleReader,
    StateStoreRecoverySafeguardBundleRetention,
    WorkflowRecoveryOutcomeRecorder,
    recovery_effect_observation_key,
    recovery_safeguard_bundle_key,
)
from fdai.runtime.control_loop_support import (
    build_workflow_recovery_effect_observation_journal,
)
from fdai.shared.contracts.models import (
    Action,
    BlastRadius,
    Mode,
    ResponseOutcome,
    ResponseOutcomeLabel,
    ResponseVerificationStatus,
    RollbackRef,
    WorkflowActionRef,
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
from fdai_service_contracts.ontology_query import content_digest

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
_TARGET = "resource:example/rg/recovery-1"
_PROCESS_ID = "process-recovery-writers-1"
_CORRELATION_ID = "correlation-recovery-writers-1"
_SOURCE_REVISION = "commit:" + "a" * 40
_EXECUTOR = "executor@example.com"
_REQUESTER = "fdai.core.workflow.recovery-requester"
_APPROVER = "approver@example.com"
_OBSERVER = "heimdall-observer@example.com"
_PROVIDER = "provider@example.com"
_FAILED_PROPOSAL = "sha256:" + "b" * 64
_BUNDLE_DIGEST = "sha256:" + "c" * 64
_RECEIPT_DIGEST = "sha256:" + "d" * 64
_ADMISSION_DIGEST = "sha256:" + "e" * 64
_COMPENSATION_RECEIPTS = ("sha256:" + "1" * 64, "sha256:" + "2" * 64)
_ACTION_TYPE = "workflow.recovery.reconcile"
_PARAMS: dict[str, object] = {"reason": "reconcile the partially applied change"}


class _Admissions:
    """Admit exactly the evidence the recovery path presents."""

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
    """Record every provider invocation the recovery path performs."""

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


def _target_digest(target_ref: str = _TARGET) -> str:
    return f"sha256:{hashlib.sha256(target_ref.encode()).hexdigest()}"


def _attempt() -> RecoveryAttemptIdentity:
    return RecoveryAttemptIdentity.create(
        process_id=_PROCESS_ID,
        failed_compensation_proposal_digest=_FAILED_PROPOSAL,
        hold_revision=1,
        recovery_action_type=_ACTION_TYPE,
        recovery_payload_digest=content_digest(
            {
                "action_type": _ACTION_TYPE,
                "params": dict(_PARAMS),
                "purpose": "workflow-recovery-payload",
            }
        ),
        target_digest=_target_digest(),
        source_revision=_SOURCE_REVISION,
        attempt_number=1,
    )


def _observation(
    *,
    observer: str = _OBSERVER,
    success: bool = True,
    authority_class: EffectEvidenceClass = EffectEvidenceClass.AUTHORITATIVE_EXTERNAL,
    final: bool = True,
) -> RecoveryEffectObservation:
    evidence = EffectEvidenceRecord(
        observer_identity=observer,
        observer_authority_class=authority_class,
        purpose_version="1.0.0",
        method_version="1.0.0",
        event_time=_NOW - timedelta(minutes=3),
        recorded_time=_NOW - timedelta(minutes=2),
        freshness_policy_seconds=600,
        completeness=True,
        provenance="azure-resource-graph",
        conflict_status="none",
        synthetic=False,
        evidence_digest="sha256:" + "7" * 64,
    )
    return RecoveryEffectObservation(
        evidence=evidence,
        observer_identity=evidence.observer_identity,
        provider_identity=_PROVIDER,
        expected_effect_digest="sha256:" + "8" * 64,
        approved_envelope_digest="sha256:" + "9" * 64,
        action_digest="sha256:" + "3" * 64,
        evidence_window_start=_NOW - timedelta(minutes=4),
        evidence_window_end=_NOW - timedelta(minutes=1),
        watermarks=(
            FinalizedWatermark(
                source_id="azure-activity-log",
                watermark=_NOW - timedelta(minutes=1),
                final=final,
                watermark_digest="sha256:" + "4" * 64,
            ),
        ),
        success=success,
    )


def _executed_action(attempt: RecoveryAttemptIdentity) -> Action:
    step_id = recovery_attempt_step_id(attempt)
    return Action(
        schema_version="1.0.0",
        action_id=uuid5(UUID("00000000-0000-0000-0000-0000000000ff"), step_id),
        event_id=uuid5(UUID("00000000-0000-0000-0000-0000000000fe"), step_id),
        idempotency_key=f"recovery-{step_id}",
        mode=Mode.ENFORCE,
        action_type=_ACTION_TYPE,
        operation="restart",
        target_resource_ref=_TARGET,
        params=dict(_PARAMS),
        stop_condition="provider_api_error_streak",
        stop_conditions=[{"kind": "provider_api_error_streak", "count": 1}],
        rollback_ref=RollbackRef(kind="state_forward_only"),
        blast_radius=BlastRadius(scope="resource"),
        citing_rules=["rule-1"],
        created_at=_NOW,
        workflow_action=WorkflowActionRef(
            process_id=_PROCESS_ID,
            step_id=step_id,
            proposal_ref=f"{_PROCESS_ID}:step:{step_id}:attempt:1",
        ),
    )


def _response(action: Action) -> ResponseOutcome:
    return ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=uuid5(UUID("00000000-0000-0000-0000-0000000000fd"), str(action.action_id)),
        idempotency_key=f"response-{action.idempotency_key}",
        action_id=action.action_id,
        event_id=action.event_id,
        action_type_id=action.action_type,
        target_digest="0" * 64,
        prediction_id="prediction-1",
        metric="availability",
        expected_min=0.99,
        expected_max=1.0,
        observed_value=1.0,
        predicted_at=_NOW,
        observation_deadline=_NOW,
        observed_at=_NOW,
        label=ResponseOutcomeLabel.VERIFIED,
        verification_status=ResponseVerificationStatus.VERIFIED,
        verification_reason="within_bounds",
        execution_mode=action.mode,
        execution_outcome="dispatched",
        decision="auto",
        evidence_refs=("effect:prediction-1",),
        recorded_at=_NOW,
    )


class _RecordingOutcomeLedger:
    """Stand in for the durable workflow outcome ledger at the call site."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def record(
        self,
        *,
        action: Action,
        execution_outcome: str,
        execution_receipt_ref: str | None,
        safeguard_bundle_digest: str | None,
        response_outcome: ResponseOutcome,
    ) -> str | None:
        del execution_receipt_ref, response_outcome
        self.calls.append((execution_outcome, safeguard_bundle_digest))
        return f"workflow-outcome:{action.idempotency_key}"


async def _snapshot(process_store: InMemoryProcessRuntimeStore) -> ProcessSnapshot:
    snapshot, _ = await process_store.create(
        snapshot=ProcessSnapshot(
            process_id=_PROCESS_ID,
            workflow_ref="recovery-flow",
            workflow_version="1",
            status=ProcessStatus.COMPENSATING,
            current_step="compensate_apply_first",
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
    return snapshot


def _journal(store: InMemoryStateStore) -> StateStoreRecoveryApprovalJournal:
    return StateStoreRecoveryApprovalJournal(
        approvals=StateStoreWorkflowApprovalProvider(store),
        requester_principal=_REQUESTER,
        clock=lambda: _NOW,
    )


def _coordinator(
    store: InMemoryStateStore,
    process_store: InMemoryProcessRuntimeStore,
    *,
    dispatcher: _Dispatcher,
    approval_requester: object | None = None,
    bind_observations: bool = True,
) -> WorkflowRecoveryCoordinator:
    journal = _journal(store)
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
        effect_observations=(
            build_workflow_recovery_effect_observation_journal(
                audit_store=store,
                environ={"FDAI_WORKFLOW_EXECUTOR_IDENTITY": _EXECUTOR},
            )
            if bind_observations
            else None
        ),
        approval_reader=journal,
        approval_requester=(  # type: ignore[arg-type]
            journal if approval_requester is None else approval_requester
        ),
        admission_provider=_Admissions(),  # type: ignore[arg-type]
        bundle_reader=StateStoreRecoverySafeguardBundleReader(store),
        clock=lambda: _NOW,
    )


async def _recover(coordinator: WorkflowRecoveryCoordinator, snapshot: ProcessSnapshot):
    return await coordinator.recover(
        snapshot=snapshot,
        failed_compensation_proposal_digest=_FAILED_PROPOSAL,
        recovery_action_type=_ACTION_TYPE,
        recovery_params=_PARAMS,
        compensation_receipt_digests=_COMPENSATION_RECEIPTS,
    )


async def _held() -> tuple[InMemoryStateStore, InMemoryProcessRuntimeStore, ProcessSnapshot]:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    process_store = InMemoryProcessRuntimeStore()
    snapshot = await _snapshot(process_store)
    await StateStoreAutomationHoldLedger(store, clock=lambda: _NOW).issue(
        target_ref=_TARGET,
        process_id=_PROCESS_ID,
        reason="compensation_failed",
    )
    return store, process_store, snapshot


async def _approve(store: InMemoryStateStore, *, approver: str = _APPROVER) -> None:
    """Record one separate human decision through the production HIL registry."""

    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    pending = await registry.list_pending(limit=10)
    assert pending, "the recovery approval request never reached the HIL queue"
    for item in pending:
        await registry.record_decision(
            idempotency_key=item.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid=approver,
            justification="recovery approved by a separate human",
        )


class TestRecoveryApprovalJournalWriter:
    async def test_missing_approval_requests_one_through_the_journal(self) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()

        result = await _recover(_coordinator(store, process_store, dispatcher=dispatcher), snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "approval_missing"
        assert dispatcher.calls == []
        attempt = _attempt()
        approval = await _journal(store).recovery_approval(
            attempt=attempt,
            process_id=_PROCESS_ID,
            target_resource_id=_TARGET,
        )
        assert approval is not None
        assert approval.step_id == recovery_attempt_step_id(attempt)
        assert approval.requester_principal == _REQUESTER
        assert approval.decisions == ()
        assert any(
            row["entry"].get("action_kind") == "workflow.recovery.approval_requested"
            for row in store.audit_entries
        )

    async def test_requesting_an_approval_never_grants_one(self) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)

        first = await _recover(coordinator, snapshot)
        second = await _recover(coordinator, snapshot)

        assert first.reason == "approval_missing"
        assert second.reason == "quorum_not_met"
        assert dispatcher.calls == []
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)

    async def test_a_human_decision_in_the_journal_admits_the_attempt(self) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)
        await _recover(coordinator, snapshot)
        await _approve(store)

        result = await _recover(coordinator, snapshot)

        assert result.reason == "safeguard_denied"
        assert len(dispatcher.calls) == 1

    async def test_an_executor_decision_is_never_admissible(self) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)
        await _recover(coordinator, snapshot)
        await _approve(store, approver=_EXECUTOR)

        result = await _recover(coordinator, snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "executor_identity_not_distinct"
        assert dispatcher.calls == []


class TestSafeguardBundleRetentionWriter:
    async def test_production_dispatch_outcome_retains_the_finalized_bundle(self) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)
        await _recover(coordinator, snapshot)
        await _approve(store)
        await _recover(coordinator, snapshot)
        attempt = _attempt()
        inner = _RecordingOutcomeLedger()
        recorder = WorkflowRecoveryOutcomeRecorder(
            inner=inner,  # type: ignore[arg-type]
            store=store,
            retention=StateStoreRecoverySafeguardBundleRetention(store),
            clock=lambda: _NOW,
        )
        action = _executed_action(attempt)

        receipt_ref = await recorder.record(
            action=action,
            execution_outcome="dispatched",
            execution_receipt_ref="provider-receipt-1",
            safeguard_bundle_digest=_BUNDLE_DIGEST,
            response_outcome=_response(action),
        )

        assert receipt_ref is not None
        assert inner.calls == [("dispatched", _BUNDLE_DIGEST)]
        retained = await store.read_state(recovery_safeguard_bundle_key(attempt))
        assert retained is not None
        assert retained["state"] == "finalized"
        assert retained["safeguard_bundle_digest"] == _BUNDLE_DIGEST
        assert retained["execution_authority"] is False
        assert (
            await StateStoreRecoverySafeguardBundleReader(store).finalized_recovery_bundle_digest(
                attempt=attempt,
                target_resource_id=_TARGET,
            )
            == _BUNDLE_DIGEST
        )

    @pytest.mark.parametrize(
        "execution_outcome",
        [
            "rejected_invariant",
            "failed",
            "publish_outcome_unknown",
            "blocked",
            "already_applied",
            "already_existed",
        ],
    )
    async def test_an_execution_that_never_dispatched_retains_nothing(
        self,
        execution_outcome: str,
    ) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)
        await _recover(coordinator, snapshot)
        await _approve(store)
        await _recover(coordinator, snapshot)
        attempt = _attempt()
        inner = _RecordingOutcomeLedger()
        recorder = WorkflowRecoveryOutcomeRecorder(
            inner=inner,  # type: ignore[arg-type]
            store=store,
            retention=StateStoreRecoverySafeguardBundleRetention(store),
            clock=lambda: _NOW,
        )
        action = _executed_action(attempt)

        await recorder.record(
            action=action,
            execution_outcome=execution_outcome,
            execution_receipt_ref="provider-receipt-1",
            safeguard_bundle_digest=_BUNDLE_DIGEST,
            response_outcome=_response(action),
        )

        assert inner.calls == [(execution_outcome, _BUNDLE_DIGEST)]
        assert await store.read_state(recovery_safeguard_bundle_key(attempt)) is None
        blocked = await _recover(coordinator, snapshot)
        assert blocked.reason == "safeguard_denied"
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)

    async def test_a_dispatch_without_a_lifecycle_receipt_retains_nothing(self) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)
        await _recover(coordinator, snapshot)
        await _approve(store)
        await _recover(coordinator, snapshot)
        attempt = _attempt()
        recorder = WorkflowRecoveryOutcomeRecorder(
            inner=_RecordingOutcomeLedger(),  # type: ignore[arg-type]
            store=store,
            retention=StateStoreRecoverySafeguardBundleRetention(store),
            clock=lambda: _NOW,
        )
        action = _executed_action(attempt)

        await recorder.record(
            action=action,
            execution_outcome="dispatched",
            execution_receipt_ref=None,
            safeguard_bundle_digest=_BUNDLE_DIGEST,
            response_outcome=_response(action),
        )

        assert await store.read_state(recovery_safeguard_bundle_key(attempt)) is None

    async def test_a_non_recovery_step_retains_nothing(self) -> None:
        store, _, _ = await _held()
        inner = _RecordingOutcomeLedger()
        recorder = WorkflowRecoveryOutcomeRecorder(
            inner=inner,  # type: ignore[arg-type]
            store=store,
            retention=StateStoreRecoverySafeguardBundleRetention(store),
            clock=lambda: _NOW,
        )
        attempt = _attempt()
        action = _executed_action(attempt).model_copy(
            update={
                "workflow_action": WorkflowActionRef(
                    process_id=_PROCESS_ID,
                    step_id="restart",
                    proposal_ref=f"{_PROCESS_ID}:step:restart:attempt:1",
                )
            }
        )

        await recorder.record(
            action=action,
            execution_outcome="dispatched",
            execution_receipt_ref="provider-receipt-1",
            safeguard_bundle_digest=_BUNDLE_DIGEST,
            response_outcome=_response(action),
        )

        assert inner.calls == [("dispatched", _BUNDLE_DIGEST)]
        assert await store.read_state(recovery_safeguard_bundle_key(attempt)) is None

    async def test_an_unbound_recovery_step_retains_nothing(self) -> None:
        store, _, _ = await _held()
        inner = _RecordingOutcomeLedger()
        recorder = WorkflowRecoveryOutcomeRecorder(
            inner=inner,  # type: ignore[arg-type]
            store=store,
            retention=StateStoreRecoverySafeguardBundleRetention(store),
            clock=lambda: _NOW,
        )
        attempt = _attempt()
        action = _executed_action(attempt)

        await recorder.record(
            action=action,
            execution_outcome="dispatched",
            execution_receipt_ref="provider-receipt-1",
            safeguard_bundle_digest=_BUNDLE_DIGEST,
            response_outcome=_response(action),
        )

        assert await store.read_state(recovery_safeguard_bundle_key(attempt)) is None


class TestEffectObservationJournalWriter:
    async def test_an_independent_observation_is_persisted_for_the_attempt(self) -> None:
        store, _, _ = await _held()
        journal = StateStoreRecoveryEffectObservationJournal(
            store=store,
            executor_identity=_EXECUTOR,
        )
        attempt = _attempt()

        recorded = await journal.record_observation(
            attempt=attempt,
            target_resource_id=_TARGET,
            provider_receipt_digest=_RECEIPT_DIGEST,
            observation=_observation(),
        )

        assert recorded is True
        stored = await store.read_state(recovery_effect_observation_key(attempt, _RECEIPT_DIGEST))
        assert stored is not None
        assert stored["observer_identity"] == _OBSERVER
        assert stored["effect_verification_authority"] is False
        assert stored["execution_authority"] is False
        observed = await StateStoreRecoveryEffectObserver(store).observe_recovery_effect(
            attempt=attempt,
            target_resource_id=_TARGET,
            provider_receipt_digest=_RECEIPT_DIGEST,
            observed_at=_NOW,
        )
        assert observed is not None
        assert observed.success is True

    @pytest.mark.parametrize(
        "observation",
        [
            _observation(observer=_EXECUTOR),
            _observation(observer=_PROVIDER),
            _observation(authority_class=EffectEvidenceClass.EXECUTOR_CONTROLLED),
            _observation(authority_class=EffectEvidenceClass.PROVIDER_DISPATCH),
            _observation(final=False),
        ],
    )
    async def test_dependent_or_synthetic_evidence_is_refused(
        self,
        observation: RecoveryEffectObservation,
    ) -> None:
        store, _, _ = await _held()
        journal = StateStoreRecoveryEffectObservationJournal(
            store=store,
            executor_identity=_EXECUTOR,
        )
        attempt = _attempt()

        recorded = await journal.record_observation(
            attempt=attempt,
            target_resource_id=_TARGET,
            provider_receipt_digest=_RECEIPT_DIGEST,
            observation=observation,
        )

        assert recorded is False
        key = recovery_effect_observation_key(attempt, _RECEIPT_DIGEST)
        assert await store.read_state(key) is None


class TestRecoveryCompletesThroughProductionWritersOnly:
    async def test_the_hold_closes_without_any_seeded_recovery_state(self) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)
        attempt = _attempt()

        requested = await _recover(coordinator, snapshot)
        assert requested.reason == "approval_missing"

        await _approve(store)
        dispatched = await _recover(coordinator, snapshot)
        assert dispatched.reason == "safeguard_denied"
        assert len(dispatcher.calls) == 1

        action = _executed_action(attempt)
        await WorkflowRecoveryOutcomeRecorder(
            inner=_RecordingOutcomeLedger(),  # type: ignore[arg-type]
            store=store,
            retention=StateStoreRecoverySafeguardBundleRetention(store),
            clock=lambda: _NOW,
        ).record(
            action=action,
            execution_outcome="dispatched",
            execution_receipt_ref="provider-receipt-1",
            safeguard_bundle_digest=_BUNDLE_DIGEST,
            response_outcome=_response(action),
        )
        unobserved = await _recover(coordinator, snapshot)
        assert unobserved.disposition is RecoveryDisposition.EFFECT_UNVERIFIED

        assert await coordinator.record_independent_observation(
            attempt=attempt,
            target_resource_id=_TARGET,
            provider_receipt_digest=_RECEIPT_DIGEST,
            observation=_observation(),
        )

        completed = await _recover(coordinator, snapshot)

        assert completed.disposition is RecoveryDisposition.COMPLETED
        assert completed.release_receipt_digest is not None
        assert completed.completion_digest is not None
        assert len(dispatcher.calls) == 1
        assert not await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)
        terminal = await process_store.get(_PROCESS_ID)
        assert terminal is not None
        assert terminal.status is ProcessStatus.COMPENSATED

    async def test_a_missing_approval_writer_stays_visibly_fail_closed(self) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()
        coordinator = WorkflowRecoveryCoordinator(
            process_store=process_store,
            audit_store=store,
            holds=StateStoreAutomationHoldLedger(store, clock=lambda: _NOW),
            config=RecoveryCoordinatorConfig(
                executor_identity=_EXECUTOR,
                source_revision=_SOURCE_REVISION,
            ),
            dispatcher=dispatcher,  # type: ignore[arg-type]
            effect_observer=StateStoreRecoveryEffectObserver(store),
            approval_reader=None,
            approval_requester=None,
            admission_provider=_Admissions(),  # type: ignore[arg-type]
            bundle_reader=StateStoreRecoverySafeguardBundleReader(store),
            clock=lambda: _NOW,
        )

        result = await _recover(coordinator, snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "approval_missing"
        assert result.recovery_incomplete is True
        assert dispatcher.calls == []
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)
        rejection = next(
            row["entry"]
            for row in store.audit_entries
            if row["entry"].get("action_kind") == "workflow.recovery.rejected"
        )
        assert rejection["reason"] == "approval_missing"
        assert rejection["recovery_incomplete"] is True


class TestRuntimeBoundObservationIntake:
    async def test_the_runtime_intake_persists_an_independent_observation(self) -> None:
        store, process_store, snapshot = await _held()
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)
        attempt = _attempt()

        recorded = await coordinator.record_independent_observation(
            attempt=attempt,
            target_resource_id=_TARGET,
            provider_receipt_digest=_RECEIPT_DIGEST,
            observation=_observation(),
        )

        assert recorded is True
        stored = await store.read_state(recovery_effect_observation_key(attempt, _RECEIPT_DIGEST))
        assert stored is not None
        assert stored["observer_identity"] == _OBSERVER

    async def test_the_runtime_intake_refuses_executor_owned_evidence(self) -> None:
        store, process_store, snapshot = await _held()
        coordinator = _coordinator(store, process_store, dispatcher=_Dispatcher())
        attempt = _attempt()

        recorded = await coordinator.record_independent_observation(
            attempt=attempt,
            target_resource_id=_TARGET,
            provider_receipt_digest=_RECEIPT_DIGEST,
            observation=_observation(observer=_EXECUTOR),
        )

        assert recorded is False
        key = recovery_effect_observation_key(attempt, _RECEIPT_DIGEST)
        assert await store.read_state(key) is None

    async def test_an_unbound_intake_stays_visibly_fail_closed(self) -> None:
        store, process_store, snapshot = await _held()
        coordinator = _coordinator(
            store,
            process_store,
            dispatcher=_Dispatcher(),
            bind_observations=False,
        )
        attempt = _attempt()

        recorded = await coordinator.record_independent_observation(
            attempt=attempt,
            target_resource_id=_TARGET,
            provider_receipt_digest=_RECEIPT_DIGEST,
            observation=_observation(),
        )

        assert recorded is False
        key = recovery_effect_observation_key(attempt, _RECEIPT_DIGEST)
        assert await store.read_state(key) is None
