"""Production call-site tests for the durable workflow recovery path.

Covers #630 #640 #652 #656 #658 at the real coordinator, not at the pure
modules it composes: missing approval, wrong approver identity, a stale
claim, duplicate and restart delivery, release-receipt crash recovery, and
automation-hold reissue inside the executor lock.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryDispatchOutcome,
    RecoveryDispatchResult,
    RecoveryPreDispatchClaim,
)
from fdai.core.workflow.recovery_coordinator import (
    RecoveryCoordinatorConfig,
    RecoveryDisposition,
    WorkflowRecoveryCoordinator,
)
from fdai.core.workflow.workflow_runtime import workflow_approval_state_key
from fdai.delivery.persistence.workflow_recovery import (
    StateStoreRecoveryApprovalReader,
    StateStoreRecoveryEffectObserver,
    StateStoreRecoverySafeguardBundleReader,
    recovery_approval_step_id,
    recovery_effect_observation_key,
    recovery_safeguard_bundle_key,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
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
_TARGET = "res-recovery-1"
_PROCESS_ID = "process-recovery-1"
_SOURCE_REVISION = "commit:" + "a" * 40
_EXECUTOR = "executor@example.com"
_REQUESTER = "requester@example.com"
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
    def __init__(self) -> None:
        self.calls = 0

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        self.calls += 1
        return DecisionEvidenceAdmission(
            receipt_digest=_ADMISSION_DIGEST,
            verification_bundle_digest="sha256:" + "f" * 64,
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
            verified_at=_NOW - timedelta(minutes=1),
            valid_until=_NOW + timedelta(minutes=10),
        )


class _Dispatcher:
    def __init__(self, *, outcome: str = RecoveryDispatchOutcome.DISPATCHED) -> None:
        self.outcome = outcome
        self.calls: list[RecoveryPreDispatchClaim] = []
        self.reconcile_calls = 0

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
            outcome=self.outcome,
            provider_receipt_digest=(
                _RECEIPT_DIGEST if self.outcome == RecoveryDispatchOutcome.DISPATCHED else None
            ),
            recorded_at=_NOW,
        )

    async def reconcile_recovery(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
    ) -> RecoveryDispatchResult | None:
        self.reconcile_calls += 1
        return RecoveryDispatchResult.create(
            attempt_identity_digest=attempt.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.DISPATCHED,
            provider_receipt_digest=_RECEIPT_DIGEST,
            recorded_at=_NOW,
        )


def _target_digest(target_ref: str = _TARGET) -> str:
    return f"sha256:{hashlib.sha256(target_ref.encode()).hexdigest()}"


def _attempt(*, hold_revision: int = 1, attempt_number: int = 1) -> RecoveryAttemptIdentity:
    return RecoveryAttemptIdentity.create(
        process_id=_PROCESS_ID,
        failed_compensation_proposal_digest=_FAILED_PROPOSAL,
        hold_revision=hold_revision,
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
        attempt_number=attempt_number,
    )


async def _seed_approval(
    store: InMemoryStateStore,
    attempt: RecoveryAttemptIdentity,
    *,
    approver: str = _APPROVER,
    state: str = "pending",
    decision: str = "approved",
    expires_at: datetime | None = None,
    decisions: tuple[tuple[str, str], ...] | None = None,
) -> None:
    step_id = recovery_approval_step_id(attempt)
    claims = decisions if decisions is not None else ((approver, decision),)
    await store.write_state(
        workflow_approval_state_key(_PROCESS_ID, step_id, attempt.attempt_number),
        {
            "process_id": _PROCESS_ID,
            "step_id": step_id,
            "attempt": attempt.attempt_number,
            "requester_principal": _REQUESTER,
            "quorum": 1,
            "no_self_approval": True,
            "requested_at": (_NOW - timedelta(minutes=5)).isoformat(),
            "expires_at": (
                expires_at.isoformat()
                if expires_at is not None
                else (_NOW + timedelta(minutes=30)).isoformat()
            ),
            "decision_claims": {
                f"slot-{index}": {
                    "principal": principal,
                    "decision": claim_decision,
                    "receipt_ref": f"approval:recovery:{index}",
                }
                for index, (principal, claim_decision) in enumerate(claims, start=1)
            },
            "state": state,
            "revision": 3,
        },
    )


async def _seed_bundle(store: InMemoryStateStore, attempt: RecoveryAttemptIdentity) -> None:
    await store.write_state(
        recovery_safeguard_bundle_key(attempt),
        {
            "attempt_identity_digest": attempt.identity_digest,
            "target_digest": attempt.target_digest,
            "target_resource_digest": _target_digest(),
            "source_revision": attempt.source_revision,
            "state": "finalized",
            "safeguard_bundle_digest": _BUNDLE_DIGEST,
            "execution_authority": False,
        },
    )


async def _seed_observation(
    store: InMemoryStateStore,
    attempt: RecoveryAttemptIdentity,
    *,
    observer: str = _OBSERVER,
    authority_class: str = "authoritative_external",
    success: bool = True,
) -> None:
    await store.write_state(
        recovery_effect_observation_key(attempt, _RECEIPT_DIGEST),
        {
            "attempt_identity_digest": attempt.identity_digest,
            "provider_receipt_digest": _RECEIPT_DIGEST,
            "observer_identity": observer,
            "provider_identity": _PROVIDER,
            "observer_authority_class": authority_class,
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
            "success": success,
        },
    )


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
            correlation_id="correlation-recovery-1",
        ),
        event=ProcessEvent(
            event_id="event-created",
            process_id=_PROCESS_ID,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key=f"{_PROCESS_ID}:created",
            recorded_at=_NOW - timedelta(hours=1),
            correlation_id="correlation-recovery-1",
        ),
    )
    return snapshot


def _coordinator(
    store: InMemoryStateStore,
    process_store: InMemoryProcessRuntimeStore,
    *,
    dispatcher: object | None,
    admissions: _Admissions | None = None,
    approval_reader: object | None = None,
    approval_requester: object | None = None,
    executor_identity: str = _EXECUTOR,
    clock: Callable[[], datetime] = lambda: _NOW,
) -> WorkflowRecoveryCoordinator:
    return WorkflowRecoveryCoordinator(
        process_store=process_store,
        audit_store=store,
        holds=StateStoreAutomationHoldLedger(store, clock=lambda: _NOW),
        config=RecoveryCoordinatorConfig(
            executor_identity=executor_identity,
            source_revision=_SOURCE_REVISION,
        ),
        dispatcher=dispatcher,  # type: ignore[arg-type]
        effect_observer=StateStoreRecoveryEffectObserver(store),
        approval_reader=(  # type: ignore[arg-type]
            approval_reader
            if approval_reader is not None
            else StateStoreRecoveryApprovalReader(store)
        ),
        approval_requester=approval_requester,  # type: ignore[arg-type]
        admission_provider=admissions if admissions is not None else _Admissions(),
        bundle_reader=StateStoreRecoverySafeguardBundleReader(store),
        clock=clock,
    )


async def _recover(
    coordinator: WorkflowRecoveryCoordinator,
    snapshot: ProcessSnapshot,
):
    return await coordinator.recover(
        snapshot=snapshot,
        failed_compensation_proposal_digest=_FAILED_PROPOSAL,
        recovery_action_type=_ACTION_TYPE,
        recovery_params=_PARAMS,
        compensation_receipt_digests=_COMPENSATION_RECEIPTS,
    )


async def _held_fixture(
    store: InMemoryStateStore | None = None,
    process_store: InMemoryProcessRuntimeStore | None = None,
) -> tuple[
    InMemoryStateStore,
    InMemoryProcessRuntimeStore,
    ProcessSnapshot,
    RecoveryAttemptIdentity,
]:
    store = store if store is not None else InMemoryStateStore(linearization_clock=lambda: _NOW)
    process_store = process_store if process_store is not None else InMemoryProcessRuntimeStore()
    snapshot = await _snapshot(process_store)
    holds = StateStoreAutomationHoldLedger(store, clock=lambda: _NOW)
    await holds.issue(target_ref=_TARGET, process_id=_PROCESS_ID, reason="compensation_failed")
    return store, process_store, snapshot, _attempt()


class TestRecoveryApprovalBinding:
    async def test_missing_approval_keeps_the_hold_in_force(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        dispatcher = _Dispatcher()
        result = await _recover(_coordinator(store, process_store, dispatcher=dispatcher), snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "approval_missing"
        assert dispatcher.calls == []
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)

    async def test_approval_for_a_different_attempt_is_not_reusable(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, _attempt(hold_revision=2, attempt_number=2))
        dispatcher = _Dispatcher()
        result = await _recover(_coordinator(store, process_store, dispatcher=dispatcher), snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "approval_missing"
        assert dispatcher.calls == []

    async def test_executor_identity_may_not_approve_its_own_recovery(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt, approver=_EXECUTOR)
        await _seed_observation(store, attempt)
        dispatcher = _Dispatcher()
        result = await _recover(_coordinator(store, process_store, dispatcher=dispatcher), snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "executor_identity_not_distinct"
        assert dispatcher.calls == []
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)

    async def test_unretained_finalized_bundle_never_releases_the_hold(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        dispatcher = _Dispatcher()
        result = await _recover(_coordinator(store, process_store, dispatcher=dispatcher), snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "safeguard_denied"
        assert result.release_receipt_digest is None
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)
        terminal = await process_store.get(_PROCESS_ID)
        assert terminal is not None
        assert terminal.status is not ProcessStatus.COMPENSATED

    async def test_executor_owned_observation_is_never_authoritative(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt, observer=_EXECUTOR)
        result = await _recover(
            _coordinator(store, process_store, dispatcher=_Dispatcher()), snapshot
        )

        assert result.disposition is RecoveryDisposition.EFFECT_UNVERIFIED
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)


class TestRecoveryDispatchClaim:
    async def test_verified_recovery_releases_the_hold_and_terminalizes(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        dispatcher = _Dispatcher()
        result = await _recover(_coordinator(store, process_store, dispatcher=dispatcher), snapshot)

        assert result.disposition is RecoveryDisposition.COMPLETED
        assert result.release_receipt_digest is not None
        assert result.completion_digest is not None
        assert len(dispatcher.calls) == 1
        assert not await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)
        events = await process_store.events(_PROCESS_ID)
        assert events[-1].kind is ProcessEventKind.RECOVERY_COMPLETED
        assert events[-1].payload["completion_digest"] == result.completion_digest
        terminal = await process_store.get(_PROCESS_ID)
        assert terminal is not None
        assert terminal.status is ProcessStatus.COMPENSATED

    async def test_restart_replays_without_a_second_dispatch(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)
        first = await _recover(coordinator, snapshot)
        replay = await _recover(coordinator, snapshot)

        assert first.disposition is RecoveryDisposition.COMPLETED
        assert replay.disposition is RecoveryDisposition.NOT_REQUIRED
        assert len(dispatcher.calls) == 1

    async def test_in_doubt_dispatch_keeps_the_hold_and_reconciles_later(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        doubtful = _Dispatcher(outcome=RecoveryDispatchOutcome.IN_DOUBT)
        coordinator = _coordinator(store, process_store, dispatcher=doubtful)
        in_doubt = await _recover(coordinator, snapshot)

        assert in_doubt.disposition is RecoveryDisposition.IN_DOUBT
        assert in_doubt.reason == "in_doubt"
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)

        reconciled = await _recover(coordinator, snapshot)
        assert doubtful.reconcile_calls == 1
        assert len(doubtful.calls) == 1
        assert reconciled.disposition is RecoveryDisposition.COMPLETED
        assert not await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)

    async def test_a_hold_reissued_after_the_claim_is_stale(self) -> None:
        store = _ReissuingHoldStore(linearization_clock=lambda: _NOW)
        _, process_store, snapshot, attempt = await _held_fixture(store)
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        dispatcher = _Dispatcher()
        store.arm()
        result = await _recover(_coordinator(store, process_store, dispatcher=dispatcher), snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "stale_hold"
        assert result.claim_digest is None
        assert dispatcher.calls == []

    async def test_a_claim_is_acquired_exactly_once_per_hold_revision(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        dispatcher = _Dispatcher(outcome=RecoveryDispatchOutcome.IN_DOUBT)
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)

        first = await _recover(coordinator, snapshot)
        second = await _recover(coordinator, snapshot)

        assert first.claim_digest == second.claim_digest
        assert len(dispatcher.calls) == 1

    async def test_a_dispatcher_outage_never_reports_non_invocation(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        result = await _recover(_coordinator(store, process_store, dispatcher=None), snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "not_invoked"
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)


class TestReleaseReceiptRecovery:
    async def test_crash_between_release_and_process_cas_heals_from_the_lookup(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture(
            process_store=_CrashingProcessStore()
        )
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)

        assert isinstance(process_store, _CrashingProcessStore)
        process_store.arm()
        with pytest.raises(RuntimeError, match="simulated crash"):
            await _recover(coordinator, snapshot)

        assert not await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)
        events = await process_store.events(_PROCESS_ID)
        assert all(event.kind is not ProcessEventKind.RECOVERY_COMPLETED for event in events)

        healed = await coordinator.heal(snapshot=snapshot)
        assert healed is not None
        assert healed.disposition is RecoveryDisposition.COMPLETED
        assert len(dispatcher.calls) == 1
        healed_events = await process_store.events(_PROCESS_ID)
        assert healed_events[-1].kind is ProcessEventKind.RECOVERY_COMPLETED

    async def test_heal_is_idempotent_after_the_terminal_commit(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        coordinator = _coordinator(store, process_store, dispatcher=_Dispatcher())
        completed = await _recover(coordinator, snapshot)
        healed = await coordinator.heal(snapshot=snapshot)

        assert completed.disposition is RecoveryDisposition.COMPLETED
        assert healed is not None
        assert healed.disposition is RecoveryDisposition.REPLAYED
        assert healed.completion_digest == completed.completion_digest
        terminal_events = [
            event
            for event in await process_store.events(_PROCESS_ID)
            if event.kind is ProcessEventKind.RECOVERY_COMPLETED
        ]
        assert len(terminal_events) == 1

    async def test_completion_outbox_records_both_deliveries(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        result = await _recover(
            _coordinator(store, process_store, dispatcher=_Dispatcher()), snapshot
        )
        assert result.completion_digest is not None
        entries, total = await store.read_state_page(
            "workflow:recovery-outbox:",
            limit=10,
            field="completion_digest",
            value=result.completion_digest,
        )
        assert total == 2
        assert {str(entry["delivery_kind"]) for entry in entries} == {
            "process_event",
            "saga_audit",
        }
        assert all(entry["delivery_state"] == "delivered" for entry in entries)


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


class _ReissuingHoldStore(InMemoryStateStore):
    """Advance the durable hold revision between the claim and its fence check."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._armed = False
        self._hold_reads = 0

    def arm(self) -> None:
        self._armed = True

    async def read_state(self, key: str):
        record = await super().read_state(key)
        if not self._armed or record is None or not key.startswith("workflow:automation-hold:"):
            return record
        self._hold_reads += 1
        if self._hold_reads < 2:
            return record
        return {**dict(record), "revision": int(record["revision"]) + 1}


class TestRecoveryAdmissionGate:
    """No provider dispatch before the full recovery admission is proven."""

    @pytest.mark.parametrize(
        ("seed", "expected_reason"),
        [
            ({"approver": _REQUESTER}, "self_approval"),
            ({"decision": "rejected"}, "approval_rejected"),
            ({"state": "cancelled"}, "approval_cancelled"),
            ({"state": "timed_out"}, "approval_timed_out"),
            (
                {"expires_at": _NOW - timedelta(minutes=1)},
                "approval_expired",
            ),
            (
                {"decisions": ((_REQUESTER, "approved"), (_EXECUTOR, "approved"))},
                "self_approval",
            ),
        ],
    )
    async def test_ineligible_approval_never_reaches_the_provider(
        self,
        seed: dict[str, object],
        expected_reason: str,
    ) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_observation(store, attempt)
        await _seed_approval(store, attempt, **seed)  # type: ignore[arg-type]
        dispatcher = _Dispatcher()
        result = await _recover(_coordinator(store, process_store, dispatcher=dispatcher), snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == expected_reason
        assert dispatcher.calls == []
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)

    async def test_quorum_not_met_never_reaches_the_provider(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_observation(store, attempt)
        await _seed_approval(store, attempt, decisions=())
        dispatcher = _Dispatcher()
        result = await _recover(_coordinator(store, process_store, dispatcher=dispatcher), snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "quorum_not_met"
        assert dispatcher.calls == []

    async def test_missing_decision_evidence_admission_never_dispatches(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_observation(store, attempt)
        await _seed_approval(store, attempt)
        dispatcher = _Dispatcher()
        coordinator = WorkflowRecoveryCoordinator(
            process_store=process_store,
            audit_store=store,
            holds=StateStoreAutomationHoldLedger(store, clock=lambda: _NOW),
            config=RecoveryCoordinatorConfig(
                executor_identity=_EXECUTOR,
                source_revision=_SOURCE_REVISION,
            ),
            dispatcher=dispatcher,
            effect_observer=StateStoreRecoveryEffectObserver(store),
            approval_reader=StateStoreRecoveryApprovalReader(store),
            admission_provider=None,
            bundle_reader=StateStoreRecoverySafeguardBundleReader(store),
            clock=lambda: _NOW,
        )
        result = await _recover(coordinator, snapshot)

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "decision_evidence_admission_missing"
        assert dispatcher.calls == []
        assert await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)

    async def test_failing_admission_provider_never_dispatches(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_observation(store, attempt)
        await _seed_approval(store, attempt)
        dispatcher = _Dispatcher()
        result = await _recover(
            _coordinator(
                store,
                process_store,
                dispatcher=dispatcher,
                admissions=_FailingAdmissions(),  # type: ignore[arg-type]
            ),
            snapshot,
        )

        assert result.disposition is RecoveryDisposition.REJECTED
        assert result.reason == "decision_evidence_provider_failed"
        assert dispatcher.calls == []


class TestExclusiveRecoveryClaim:
    """One exclusive in-flight claim owns the single provider invocation."""

    async def test_concurrent_recovery_dispatches_exactly_once(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        dispatcher = _BlockingDispatcher()
        winner = _coordinator(store, process_store, dispatcher=dispatcher)
        loser = _coordinator(store, process_store, dispatcher=dispatcher)

        winning = asyncio.create_task(_recover(winner, snapshot))
        await asyncio.wait_for(dispatcher.entered.wait(), timeout=5)
        losing = await asyncio.wait_for(_recover(loser, snapshot), timeout=5)
        dispatcher.release.set()
        won = await asyncio.wait_for(winning, timeout=5)

        assert len(dispatcher.calls) == 1
        assert won.disposition is RecoveryDisposition.COMPLETED
        assert losing.disposition is RecoveryDisposition.IN_DOUBT
        assert losing.reason == "in_doubt"

    async def test_the_loser_waits_without_reissuing_a_hold(self) -> None:
        store, process_store, snapshot, attempt = await _held_fixture()
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        dispatcher = _BlockingDispatcher()
        winner = _coordinator(store, process_store, dispatcher=dispatcher)
        loser = _coordinator(store, process_store, dispatcher=dispatcher)

        winning = asyncio.create_task(_recover(winner, snapshot))
        await asyncio.wait_for(dispatcher.entered.wait(), timeout=5)
        await asyncio.wait_for(_recover(loser, snapshot), timeout=5)
        dispatcher.release.set()
        await asyncio.wait_for(winning, timeout=5)

        holds = StateStoreAutomationHoldLedger(store)
        assert not await holds.is_held(target_ref=_TARGET)
        after = await _recover(loser, snapshot)
        assert after.disposition is RecoveryDisposition.NOT_REQUIRED
        assert not await holds.is_held(target_ref=_TARGET)
        assert len(dispatcher.calls) == 1
        terminal_events = [
            event
            for event in await process_store.events(_PROCESS_ID)
            if event.kind is ProcessEventKind.RECOVERY_COMPLETED
        ]
        assert len(terminal_events) == 1


class TestLateCrashHealing:
    """A consumed release heals the Process after the claim validity closed."""

    async def _crashed(
        self,
    ) -> tuple[InMemoryStateStore, _CrashingProcessStore, ProcessSnapshot, _Dispatcher]:
        process_store = _CrashingProcessStore()
        store, _, snapshot, attempt = await _held_fixture(process_store=process_store)
        await _seed_bundle(store, attempt)
        await _seed_approval(store, attempt)
        await _seed_observation(store, attempt)
        dispatcher = _Dispatcher()
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)
        process_store.arm()
        with pytest.raises(RuntimeError, match="simulated crash"):
            await _recover(coordinator, snapshot)
        assert not await StateStoreAutomationHoldLedger(store).is_held(target_ref=_TARGET)
        return store, process_store, snapshot, dispatcher

    async def test_heal_terminalizes_after_the_claim_validity_expired(self) -> None:
        store, process_store, snapshot, dispatcher = await self._crashed()
        late = _NOW + timedelta(hours=6)
        coordinator = _coordinator(
            store,
            process_store,
            dispatcher=dispatcher,
            clock=lambda: late,
        )

        healed = await coordinator.heal(snapshot=snapshot)

        assert healed is not None
        assert healed.disposition is RecoveryDisposition.COMPLETED
        assert healed.release_receipt_digest is not None
        assert len(dispatcher.calls) == 1
        events = await process_store.events(_PROCESS_ID)
        assert events[-1].kind is ProcessEventKind.RECOVERY_COMPLETED

    async def test_heal_rejects_a_release_the_hold_no_longer_proves(self) -> None:
        store, process_store, snapshot, dispatcher = await self._crashed()
        hold_key = next(key for key in store._state if key.startswith("workflow:automation-hold:"))
        record = await store.read_state(hold_key)
        assert record is not None
        await store.write_state(
            hold_key,
            {
                **dict(record),
                "consumed_recovery_admission_digest": "sha256:" + "9" * 64,
            },
        )
        late = _NOW + timedelta(hours=6)
        coordinator = _coordinator(
            store,
            process_store,
            dispatcher=dispatcher,
            clock=lambda: late,
        )

        healed = await coordinator.heal(snapshot=snapshot)

        assert healed is not None
        assert healed.disposition is RecoveryDisposition.EFFECT_UNVERIFIED
        assert healed.reason == "release_receipt_missing"
        events = await process_store.events(_PROCESS_ID)
        assert all(event.kind is not ProcessEventKind.RECOVERY_COMPLETED for event in events)

    async def test_heal_rejects_a_hold_reissued_after_the_release(self) -> None:
        store, process_store, snapshot, dispatcher = await self._crashed()
        await StateStoreAutomationHoldLedger(store, clock=lambda: _NOW).issue(
            target_ref=_TARGET,
            process_id=_PROCESS_ID,
            reason="compensation_failed_again",
        )
        late = _NOW + timedelta(hours=6)
        coordinator = _coordinator(
            store,
            process_store,
            dispatcher=dispatcher,
            clock=lambda: late,
        )

        healed = await coordinator.heal(snapshot=snapshot)

        assert healed is not None
        assert healed.disposition is RecoveryDisposition.EFFECT_UNVERIFIED
        events = await process_store.events(_PROCESS_ID)
        assert all(event.kind is not ProcessEventKind.RECOVERY_COMPLETED for event in events)

    async def test_heal_rejects_a_superseded_completion_claim(self) -> None:
        store, process_store, snapshot, dispatcher = await self._crashed()
        effect_key = next(
            key for key in store._state if key.startswith("workflow:recovery-effect:")
        )
        record = await store.read_state(effect_key)
        assert record is not None
        claims = [dict(claim) for claim in list(record["claims"])]
        claims[-1]["superseded_by"] = "sha256:" + "5" * 64
        await store.write_state(effect_key, {**dict(record), "claims": claims})
        coordinator = _coordinator(store, process_store, dispatcher=dispatcher)

        healed = await coordinator.heal(snapshot=snapshot)

        assert healed is None
        events = await process_store.events(_PROCESS_ID)
        assert all(event.kind is not ProcessEventKind.RECOVERY_COMPLETED for event in events)


class _FailingAdmissions:
    """Fail every admission so recovery stays fail-closed."""

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        del evidence_digest, scope_digest, purpose_id, source_revision
        raise TimeoutError("decision evidence admission provider is unavailable")


class _BlockingDispatcher(_Dispatcher):
    """Hold one provider invocation open so a concurrent caller can race it."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

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
        self.entered.set()
        await self.release.wait()
        return await super().dispatch_recovery(
            attempt=attempt,
            claim=claim,
            safeguard_bundle_digest=safeguard_bundle_digest,
            target_resource_id=target_resource_id,
            params=params,
            correlation_id=correlation_id,
        )
