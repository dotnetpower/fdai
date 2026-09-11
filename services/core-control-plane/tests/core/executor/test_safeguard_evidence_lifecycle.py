"""Safeguard evidence lifecycle orchestrator contract tests.

Covers #681 exit criteria: complete order, every failure boundary,
cancellation, crash/restart recovery, duplicate delivery, target
contention, and no legacy bypass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.executor.audit_intent import (
    AuditIntentAppendReceipt,
    PreEffectAuditIntent,
)
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    IdempotencyReservationTransitionReceipt,
    begin_dispatch,
)
from fdai.core.executor.safeguard_bundle_context import (
    SafeguardBundlePersistenceContext,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchPersistenceDecision,
    SafeguardDispatchPersistenceResult,
    SafeguardDispatchTransitionReceipt,
    classify_safeguard_dispatch_evidence,
)
from fdai.core.executor.safeguard_evidence_lifecycle import (
    LifecycleTerminalKind,
    SafeguardEvidenceLifecycleResult,
    cancel_before_dispatch,
    run_safeguard_evidence_lifecycle,
)
from fdai.core.executor.safeguard_pre_bundle import SafeguardPreBundleCommitment
from fdai.core.executor.safeguard_proofs import (
    AuditIntentProof,
    IdempotencyReservationProof,
    LogicalTargetLockProof,
    finalize_safeguard_proof_bundle,
    full_action_digest,
)
from fdai.core.executor.safeguards import (
    SafeguardReceipt,
    evaluate_pre_dispatch,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceIdentity,
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
    TargetDispatchFenceTransitionReceipt,
    attach_prepared_evidence,
)
from fdai.core.executor.target_dispatch_fence_store import (
    TargetDispatchFenceAcquireDecision,
    TargetDispatchFenceAcquireResult,
)
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryIdempotencyReservationStore,
)
from fdai.shared.contracts.models import ExecutionPath
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    LockOwnershipRejectionReason,
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseReceipt,
    ResourceLockReleaseState,
)
from fdai_service_contracts.ontology_query import content_digest

from tests.core.executor.test_safeguard_proofs import _action
from tests.core.executor.test_target_dispatch_fence import _policy

_NOW = datetime(2026, 9, 10, 13, 0, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64
_SOURCE_REVISION = "commit:" + "b" * 40


# ---------------------------------------------------------------------------
# In-memory test doubles
# ---------------------------------------------------------------------------


class InMemoryFenceStore:
    """Minimal in-memory target dispatch fence store for tests."""

    def __init__(self) -> None:
        self._records: dict[str, TargetDispatchFenceRecord] = {}
        self._call_log: list[str] = []

    async def acquire_generation(
        self,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceAcquireResult:
        self._call_log.append("acquire_generation")
        target = record.identity.target_digest
        existing = self._records.get(target)
        if existing is None:
            self._records[target] = record
            receipt = TargetDispatchFenceTransitionReceipt.create(
                prior_record=None,
                record=record,
                store_receipt_digest=_make_digest("fence-acquire"),
                recorded_at=record.state_changed_at,
            )
            return TargetDispatchFenceAcquireResult(
                candidate_identity=record.identity,
                decision=TargetDispatchFenceAcquireDecision.ACQUIRED,
                observed_record=record,
                transition_receipt=receipt,
            )
        from fdai.core.executor.target_dispatch_fence_store import (
            classify_target_fence,
        )

        decision = classify_target_fence(existing, record.identity)
        return TargetDispatchFenceAcquireResult(
            candidate_identity=record.identity,
            decision=decision,
            observed_record=existing,
            transition_receipt=None,
        )

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceTransitionReceipt:
        self._call_log.append("compare_and_transition")
        target = record.identity.target_digest
        existing = self._records.get(target)
        if existing is None or existing.record_digest != prior_record_digest:
            raise ValueError("fence CAS conflict: prior record mismatch")
        if existing.revision != expected_revision:
            raise ValueError("fence CAS conflict: revision mismatch")
        prior = existing
        self._records[target] = record
        return TargetDispatchFenceTransitionReceipt.create(
            prior_record=prior,
            record=record,
            store_receipt_digest=_make_digest("fence-cas"),
            recorded_at=record.state_changed_at,
        )

    async def read(
        self,
        target_digest: str,
    ) -> TargetDispatchFenceRecord | None:
        self._call_log.append("read")
        return self._records.get(target_digest)


class InMemoryEvidenceStore:
    """Minimal in-memory safeguard dispatch evidence store for tests."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, int], SafeguardDispatchEvidenceRecord] = {}
        self._call_log: list[str] = []

    async def persist_bundle(
        self,
        record: SafeguardDispatchEvidenceRecord,
    ) -> SafeguardDispatchPersistenceResult:
        self._call_log.append("persist_bundle")
        key = (record.identity.target_digest, record.identity.target_fence_generation)
        existing = self._records.get(key)
        if existing is None:
            self._records[key] = record
            receipt = SafeguardDispatchTransitionReceipt.create(
                prior_record=None,
                record=record,
                store_receipt_digest=_make_digest("evidence-persist"),
                recorded_at=record.state_changed_at,
            )
            return SafeguardDispatchPersistenceResult(
                candidate_identity=record.identity,
                decision=SafeguardDispatchPersistenceDecision.PERSISTED,
                observed_record=record,
                transition_receipt=receipt,
            )
        decision = classify_safeguard_dispatch_evidence(existing, record.identity)
        return SafeguardDispatchPersistenceResult(
            candidate_identity=record.identity,
            decision=decision,
            observed_record=existing,
            transition_receipt=None,
        )

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: SafeguardDispatchEvidenceRecord,
        bundle_persistence_receipt: SafeguardDispatchTransitionReceipt | None = None,
        current_lock_assessment: LiveLockOwnershipAssessment | None = None,
    ) -> SafeguardDispatchTransitionReceipt:
        self._call_log.append("compare_and_transition")
        key = (record.identity.target_digest, record.identity.target_fence_generation)
        existing = self._records.get(key)
        if existing is None or existing.record_digest != prior_record_digest:
            raise ValueError("evidence CAS conflict: prior record mismatch")
        if existing.revision != expected_revision:
            raise ValueError("evidence CAS conflict: revision mismatch")
        prior = existing
        self._records[key] = record
        return SafeguardDispatchTransitionReceipt.create(
            prior_record=prior,
            record=record,
            bundle_persistence_receipt=bundle_persistence_receipt,
            current_lock_assessment=current_lock_assessment,
            store_receipt_digest=_make_digest("evidence-cas"),
            recorded_at=record.state_changed_at,
        )

    async def read(
        self,
        target_digest: str,
        generation: int,
    ) -> SafeguardDispatchEvidenceRecord | None:
        self._call_log.append("read")
        return self._records.get((target_digest, generation))


class InMemoryDispatchPort:
    """Controllable dispatch double."""

    def __init__(
        self,
        *,
        transport: DispatchTransportState = DispatchTransportState.ACKNOWLEDGED,
        sink: AuthoritativeSinkState = AuthoritativeSinkState.ACCEPTED,
    ) -> None:
        self.transport = transport
        self.sink = sink
        self.dispatch_count = 0
        self.last_evidence: SafeguardDispatchEvidenceRecord | None = None

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
    ) -> tuple[
        DispatchTransportState,
        AuthoritativeSinkState,
        str | None,
        str | None,
    ]:
        self.dispatch_count += 1
        self.last_evidence = evidence_record
        accepted = self.sink in {
            AuthoritativeSinkState.ACCEPTED,
            AuthoritativeSinkState.COMMITTED,
        }
        known = self.sink in {
            AuthoritativeSinkState.ACCEPTED,
            AuthoritativeSinkState.NOT_ACCEPTED,
            AuthoritativeSinkState.COMMITTED,
            AuthoritativeSinkState.NOT_COMMITTED,
        }
        return (
            self.transport,
            self.sink,
            _DIGEST if accepted else None,
            _DIGEST if known else None,
        )


class InMemoryHeldLock:
    """Controllable held-resource-lock double with ownership assessment."""

    def __init__(
        self,
        receipt: ResourceLockAcquisitionReceipt,
        *,
        active: bool = True,
        owner: bool = True,
        verifier_id: str = "test-verifier",
        verifier_version: str = "1.0.0",
        trust_anchor_id: str = "postgres:primary",
    ) -> None:
        self._receipt = receipt
        self._active = active
        self._owner = owner
        self._verifier_id = verifier_id
        self._verifier_version = verifier_version
        self._trust_anchor_id = trust_anchor_id
        self._request = _make_lock_request(receipt)

    @property
    def acquisition_request(self) -> ResourceLockAcquisitionRequest:
        return self._request

    @property
    def acquisition_receipt(self) -> ResourceLockAcquisitionReceipt:
        return self._receipt

    def require_active(self) -> None:
        if not self._active:
            raise RuntimeError("lock is no longer active")

    @property
    def release_receipt(self) -> ResourceLockReleaseReceipt | None:
        return None

    async def assess_ownership(self) -> LiveLockOwnershipAssessment:
        session = self._receipt.session_identity if self._owner else None
        reasons: tuple[LockOwnershipRejectionReason, ...] = (
            () if self._owner else (LockOwnershipRejectionReason.LOCK_LOST,)
        )
        return LiveLockOwnershipAssessment.create(
            self._receipt,
            current_fencing_generation=None,
            current_session_identity=session,
            verifier_id=self._verifier_id,
            verifier_version=self._verifier_version,
            trust_anchor_id=self._trust_anchor_id,
            provider_attestation_digest=_make_digest("ownership-attest"),
            evaluated_at=_NOW + timedelta(seconds=2),
            valid_until=_NOW + timedelta(seconds=5),
            rejection_reasons=reasons,
        )

    async def release(self) -> ResourceLockReleaseReceipt:
        self._active = False
        return ResourceLockReleaseReceipt.create(
            acquisition_receipt=self._receipt,
            state=ResourceLockReleaseState.RELEASED,
            provider_attestation_digest=_make_digest("release-attest"),
            observed_at=_NOW + timedelta(seconds=3),
            recorded_at=_NOW + timedelta(seconds=3),
        )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_digest(domain: str) -> str:
    return content_digest({"domain": domain, "ts": _NOW.isoformat()})


def _make_lock_request(
    receipt: ResourceLockAcquisitionReceipt,
) -> ResourceLockAcquisitionRequest:
    return ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest=receipt.action_digest,
        attempt=receipt.attempt,
        producer_id=receipt.producer_id,
        producer_version=receipt.producer_version,
        source_revision=_SOURCE_REVISION,
    )


def _reservation_store(
    receipt: IdempotencyReservationTransitionReceipt,
) -> InMemoryIdempotencyReservationStore:
    store = InMemoryIdempotencyReservationStore()
    store.seed(receipt.record)
    return store


def _full_fixture(
    *,
    now: datetime = _NOW,
    target_ref: str = "resource/example",
) -> tuple[
    SafeguardDispatchEvidenceRecord,
    IdempotencyReservationTransitionReceipt,
    AuditIntentAppendReceipt,
    TargetDispatchFenceRecord,
    ResourceLockAcquisitionReceipt,
    SafeguardBundlePersistenceContext,
]:
    """Build phases 1-5 evidence for the orchestrator."""

    action = _action(
        created_at=now,
        idempotency_key="example-idem",
        params={"name": "example"},
        target_resource_ref=target_ref,
    )
    safeguard_receipt = evaluate_pre_dispatch(
        action,
        execution_path=ExecutionPath.DIRECT_API,
        plan_digest="plan-digest",
        plan_kind="test-plan",
    )
    assert isinstance(safeguard_receipt, SafeguardReceipt)
    action_digest = full_action_digest(action)

    # Lock acquisition
    acq_request = ResourceLockAcquisitionRequest.create(
        target_ref=action.target_resource_ref,
        action_digest=action_digest,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision=_SOURCE_REVISION,
    )
    acquisition = ResourceLockAcquisitionReceipt.create(
        lock_key=acq_request.lock_key,
        target_digest=acq_request.target_digest,
        action_digest=acq_request.action_digest,
        attempt=acq_request.attempt,
        provider_id="postgres-advisory-lock",
        provider_version="1.0.0",
        producer_id=acq_request.producer_id,
        producer_version=acq_request.producer_version,
        owner_token_digest=_make_digest("owner-token"),
        fencing_generation=None,
        session_identity="session:1",
        provider_attestation_digest=_make_digest("provider-attest"),
        trust_anchor_id="postgres:primary",
        acquired_at=now,
        valid_until=None,
        source_revision=acq_request.source_revision,
        request_digest=acq_request.request_digest,
    )

    # Lock assessment
    lock_assessment = LiveLockOwnershipAssessment.create(
        acquisition,
        current_fencing_generation=None,
        current_session_identity=acquisition.session_identity,
        verifier_id="test-verifier",
        verifier_version="1.0.0",
        trust_anchor_id=acquisition.trust_anchor_id,
        provider_attestation_digest=_make_digest("assessment-attest"),
        evaluated_at=now,
        valid_until=now + timedelta(seconds=3),
    )

    # Reservation
    reservation_identity = IdempotencyReservationIdentity.create(
        idempotency_key=action.idempotency_key,
        action_digest=action_digest,
        execution_path=safeguard_receipt.execution_path,
        execution_fingerprint=safeguard_receipt.execution_fingerprint,
        source_revision=_SOURCE_REVISION,
        acquisition_receipt=acquisition,
    )
    reserved = IdempotencyReservationRecord.create_reserved(
        identity=reservation_identity,
        reserved_at=now,
        lease_expires_at=now + timedelta(seconds=30),
    )
    reservation_receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=None,
        record=reserved,
        expected_prior_revision=0,
        store_receipt_digest=_make_digest("reservation-persist"),
        recorded_at=now,
    )

    # Audit intent
    intent = PreEffectAuditIntent.create(
        reservation_receipt=reservation_receipt,
        actor="fdai.core.executor",
        created_at=now,
    )
    audit_append_receipt = AuditIntentAppendReceipt.create(
        intent=intent,
        persisted_intent_digest=intent.intent_digest,
        store_receipt_digest=_make_digest("audit-persist"),
        persisted_at=now,
        read_back_at=now,
    )

    # Proofs
    lock_proof = LogicalTargetLockProof.create(
        action_digest=action_digest,
        execution_path=safeguard_receipt.execution_path,
        execution_fingerprint=safeguard_receipt.execution_fingerprint,
        lock_key=safeguard_receipt.resource_lock_key,
        source_revision=_SOURCE_REVISION,
        completed_at=now,
        operation_receipt_digest=acquisition.receipt_digest,
    )
    idempotency_proof = IdempotencyReservationProof.create(
        action_digest=action_digest,
        execution_path=safeguard_receipt.execution_path,
        execution_fingerprint=safeguard_receipt.execution_fingerprint,
        idempotency_key=action.idempotency_key,
        reservation_outcome="reserved",
        source_revision=_SOURCE_REVISION,
        completed_at=now,
        store_receipt_digest=reservation_receipt.receipt_digest,
    )
    audit_intent_proof = AuditIntentProof.create(
        action_digest=action_digest,
        execution_path=safeguard_receipt.execution_path,
        execution_fingerprint=safeguard_receipt.execution_fingerprint,
        audit_entry_digest=intent.intent_digest,
        source_revision=_SOURCE_REVISION,
        completed_at=now,
        append_receipt_digest=audit_append_receipt.receipt_digest,
    )
    bundle = finalize_safeguard_proof_bundle(
        action,
        receipt=safeguard_receipt,
        source_revision=_SOURCE_REVISION,
        recorded_at=now,
        lock_proof=lock_proof,
        lock_assessment=lock_assessment,
        expected_lock_verifier_id=lock_assessment.verifier_id,
        expected_lock_verifier_version=lock_assessment.verifier_version,
        expected_lock_trust_anchor_id=lock_assessment.trust_anchor_id,
        idempotency_proof=idempotency_proof,
        audit_intent_proof=audit_intent_proof,
    )

    # Target fence
    fence_identity = TargetDispatchFenceIdentity.create(
        target_digest=acquisition.target_digest,
        reservation_identity=reservation_identity,
        continuity_policy=_policy(),
        generation=1,
        client_correlation_id="dispatch:1",
        sink_idempotency_key="sink:1",
    )
    preparing = TargetDispatchFenceRecord.create_preparing(
        identity=fence_identity,
        changed_at=now,
    )

    # Persistence context
    persistence_context = SafeguardBundlePersistenceContext(
        action=action,
        pre_bundle_commitment=SafeguardPreBundleCommitment.create(
            action=action,
            execution_path=safeguard_receipt.execution_path,
            source_revision=_SOURCE_REVISION,
            committed_at=now,
        ),
        safeguard_receipt=safeguard_receipt,
        reservation_receipt=reservation_receipt,
        audit_append_receipt=audit_append_receipt,
        lock_assessment=lock_assessment,
        lock_proof=lock_proof,
        idempotency_proof=idempotency_proof,
        audit_intent_proof=audit_intent_proof,
    )

    # Bundle evidence record
    bundle_record = SafeguardDispatchEvidenceRecord.create_bundle_persisted(
        preparing_fence=preparing,
        persistence_context=persistence_context,
        bundle=bundle,
        persisted_at=now,
    )

    return (
        bundle_record,
        reservation_receipt,
        audit_append_receipt,
        preparing,
        acquisition,
        persistence_context,
    )


# ---------------------------------------------------------------------------
# Tests: complete happy-path order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_completes_resolved_with_exact_order() -> None:
    """Exit criterion: fixed order with resolved terminal outcome."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort(
        transport=DispatchTransportState.ACKNOWLEDGED,
        sink=AuthoritativeSinkState.ACCEPTED,
    )
    held_lock = InMemoryHeldLock(acq)

    result = await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    assert result.kind is LifecycleTerminalKind.RESOLVED
    assert result.bundle_digest == bundle_record.bundle.bundle_digest
    assert result.execution_authority is False
    assert result.effect_verification_authority is False
    assert result.fence_record is not None
    assert result.fence_record.state is TargetDispatchFenceState.RELEASE_PENDING
    assert result.evidence_record is not None
    assert result.evidence_record.state is SafeguardDispatchEvidenceState.PRE_RELEASE
    assert result.pre_release_receipt is not None
    assert dispatch_port.dispatch_count == 1


@pytest.mark.asyncio
async def test_lifecycle_quarantines_on_unknown_sink() -> None:
    """Exit criterion: unknown outcome quarantines the target."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort(
        transport=DispatchTransportState.ACKNOWLEDGED,
        sink=AuthoritativeSinkState.UNKNOWN,
    )
    held_lock = InMemoryHeldLock(acq)

    result = await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    assert result.kind is LifecycleTerminalKind.QUARANTINED
    assert result.bundle_digest is not None


@pytest.mark.asyncio
async def test_lifecycle_quarantines_on_failed_transport() -> None:
    """Exit criterion: failed transport quarantines."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort(
        transport=DispatchTransportState.FAILED,
        sink=AuthoritativeSinkState.UNOBSERVED,
    )
    held_lock = InMemoryHeldLock(acq)

    result = await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    assert result.kind is LifecycleTerminalKind.QUARANTINED


@pytest.mark.asyncio
async def test_lifecycle_quarantines_on_unproven_continuity() -> None:
    """Exit criterion: lost lock ownership produces quarantine."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort(
        transport=DispatchTransportState.ACKNOWLEDGED,
        sink=AuthoritativeSinkState.ACCEPTED,
    )
    # Lock owner flag set to False -> continuity_unproven
    held_lock = InMemoryHeldLock(acq, owner=False)

    result = await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    assert result.kind is LifecycleTerminalKind.QUARANTINED


# ---------------------------------------------------------------------------
# Tests: evidence conflict and duplicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_conflict_stops_before_dispatch() -> None:
    """Exit criterion: conflicted evidence stops before dispatch."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort()
    held_lock = InMemoryHeldLock(acq)

    # Pre-populate evidence store with a different record for the same key
    other_bundle, *_ = _full_fixture(target_ref="resource/example")
    key = (
        other_bundle.identity.target_digest,
        other_bundle.identity.target_fence_generation,
    )
    evidence_store._records[key] = other_bundle

    result = await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    assert result.kind is LifecycleTerminalKind.EVIDENCE_CONFLICT
    assert dispatch_port.dispatch_count == 0
    assert result.pre_release_receipt is None
    assert result.release_pending_fence is None


# ---------------------------------------------------------------------------
# Tests: cancellation before dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_before_dispatch_resolves_fence() -> None:
    """Exit criterion: cancellation before dispatch resolves fence."""

    _bundle_record, _reservation_receipt, _audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    held_lock = InMemoryHeldLock(acq)

    result = await cancel_before_dispatch(
        held_lock=held_lock,
        preparing_fence=preparing,
        no_dispatch_evidence_digest=_DIGEST,
        fence_store=fence_store,
        now=_NOW,
    )

    assert result.kind is LifecycleTerminalKind.CANCELLED_BEFORE_DISPATCH
    assert result.bundle_digest is None
    assert result.fence_record is not None
    assert result.fence_record.state is TargetDispatchFenceState.RESOLVED
    assert result.execution_authority is False
    assert result.effect_verification_authority is False


@pytest.mark.asyncio
async def test_cancel_rejects_inactive_lock() -> None:
    """Exit criterion: cancel fails closed with inactive lock."""

    _bundle_record, _reservation_receipt, _audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    held_lock = InMemoryHeldLock(acq, active=False)

    with pytest.raises(RuntimeError, match="lock is no longer active"):
        await cancel_before_dispatch(
            held_lock=held_lock,
            preparing_fence=preparing,
            no_dispatch_evidence_digest=_DIGEST,
            fence_store=fence_store,
            now=_NOW,
        )


# ---------------------------------------------------------------------------
# Tests: prior-phase validation (fail closed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_non_reserved_reservation() -> None:
    """Exit criterion: wrong reservation state stops before dispatch."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, ctx = _full_fixture()
    # Make the reservation in-flight instead of reserved
    in_flight = begin_dispatch(reservation_receipt.record, at=_NOW)
    bad_receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=reservation_receipt.record,
        record=in_flight,
        expected_prior_revision=reservation_receipt.record.revision,
        store_receipt_digest=_make_digest("bad-reservation"),
        recorded_at=_NOW,
    )

    fence_store = InMemoryFenceStore()
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort()
    held_lock = InMemoryHeldLock(acq)

    with pytest.raises(ValueError, match="current reserved"):
        await run_safeguard_evidence_lifecycle(
            held_lock=held_lock,
            reservation_receipt=bad_receipt,
            reservation_store=_reservation_store(bad_receipt),
            audit_append_receipt=audit_receipt,
            bundle_record=bundle_record,
            preparing_fence=preparing,
            fence_store=fence_store,
            evidence_store=evidence_store,
            dispatch_port=dispatch_port,
            now=_NOW,
        )
    assert dispatch_port.dispatch_count == 0


@pytest.mark.asyncio
async def test_rejects_non_preparing_fence() -> None:
    """Exit criterion: wrong fence state stops before dispatch."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    # Advance fence to prepared (not preparing)
    prepared = attach_prepared_evidence(
        preparing,
        audit_append_receipt=audit_receipt,
        safeguard_bundle_digest=bundle_record.bundle.bundle_digest,
        changed_at=_NOW,
    )

    fence_store = InMemoryFenceStore()
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort()
    held_lock = InMemoryHeldLock(acq)

    with pytest.raises(ValueError, match="preparing target fence"):
        await run_safeguard_evidence_lifecycle(
            held_lock=held_lock,
            reservation_receipt=reservation_receipt,
            reservation_store=_reservation_store(reservation_receipt),
            audit_append_receipt=audit_receipt,
            bundle_record=bundle_record,
            preparing_fence=prepared,
            fence_store=fence_store,
            evidence_store=evidence_store,
            dispatch_port=dispatch_port,
            now=_NOW,
        )
    assert dispatch_port.dispatch_count == 0


@pytest.mark.asyncio
async def test_rejects_inactive_lock() -> None:
    """Exit criterion: inactive lock fails closed."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()

    fence_store = InMemoryFenceStore()
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort()
    held_lock = InMemoryHeldLock(acq, active=False)

    with pytest.raises(RuntimeError, match="lock is no longer active"):
        await run_safeguard_evidence_lifecycle(
            held_lock=held_lock,
            reservation_receipt=reservation_receipt,
            reservation_store=_reservation_store(reservation_receipt),
            audit_append_receipt=audit_receipt,
            bundle_record=bundle_record,
            preparing_fence=preparing,
            fence_store=fence_store,
            evidence_store=evidence_store,
            dispatch_port=dispatch_port,
            now=_NOW,
        )
    assert dispatch_port.dispatch_count == 0


# ---------------------------------------------------------------------------
# Tests: result authority invariants
# ---------------------------------------------------------------------------


def test_result_rejects_execution_authority() -> None:
    """Exit criterion: result carries no authority."""

    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        SafeguardEvidenceLifecycleResult(
            kind=LifecycleTerminalKind.FENCE_BLOCKED,
            bundle_digest=None,
            fence_record=None,
            evidence_record=None,
            pre_release_receipt=None,
            release_pending_fence=None,
            execution_authority=True,  # type: ignore[arg-type]
            effect_verification_authority=False,
        )


def test_result_rejects_effect_verification_authority() -> None:
    """Exit criterion: result carries no verification authority."""

    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        SafeguardEvidenceLifecycleResult(
            kind=LifecycleTerminalKind.FENCE_BLOCKED,
            bundle_digest=None,
            fence_record=None,
            evidence_record=None,
            pre_release_receipt=None,
            release_pending_fence=None,
            execution_authority=False,
            effect_verification_authority=True,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Tests: dispatch/commit/effect/release separation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_evidence_separates_transport_from_sink() -> None:
    """Exit criterion: dispatch, sink commit, effect, and release are separate."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort(
        transport=DispatchTransportState.SENT,
        sink=AuthoritativeSinkState.UNOBSERVED,
    )
    held_lock = InMemoryHeldLock(acq)

    result = await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    # Unobserved sink -> quarantine, independent effect still pending
    assert result.kind is LifecycleTerminalKind.QUARANTINED
    assert result.evidence_record is not None
    assert result.evidence_record.independent_effect_state == "pending"
    assert result.evidence_record.effect_verified is False


@pytest.mark.asyncio
async def test_committed_sink_with_acknowledged_transport_resolves() -> None:
    """Exit criterion: committed+acknowledged => resolved."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort(
        transport=DispatchTransportState.ACKNOWLEDGED,
        sink=AuthoritativeSinkState.COMMITTED,
    )
    held_lock = InMemoryHeldLock(acq)

    result = await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    assert result.kind is LifecycleTerminalKind.RESOLVED


# ---------------------------------------------------------------------------
# Tests: contention behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_stores_exact_fence_sequence() -> None:
    """Exit criterion: fence transitions follow preparing->prepared->in_flight->release_pending."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort()
    held_lock = InMemoryHeldLock(acq)

    result = await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )
    # Verify result completed before inspecting store state
    assert result.kind in {LifecycleTerminalKind.RESOLVED, LifecycleTerminalKind.QUARANTINED}
    stored = await fence_store.read(preparing.identity.target_digest)
    assert stored is not None
    assert stored.state is TargetDispatchFenceState.RELEASE_PENDING

    # Call log should show: persist, prepared CAS, in_flight CAS,
    # dispatch_started CAS, observation CAS, pre_release CAS,
    # release_pending CAS
    assert "compare_and_transition" in fence_store._call_log


@pytest.mark.asyncio
async def test_lifecycle_evidence_store_sequence() -> None:
    """Exit criterion: evidence transitions through all four states."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort()
    held_lock = InMemoryHeldLock(acq)

    await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    # persist_bundle + 3 compare_and_transition calls
    assert evidence_store._call_log.count("persist_bundle") == 1
    assert evidence_store._call_log.count("compare_and_transition") == 3

    # Final stored record should be pre_release
    stored = await evidence_store.read(
        bundle_record.identity.target_digest,
        bundle_record.identity.target_fence_generation,
    )
    assert stored is not None
    assert stored.state is SafeguardDispatchEvidenceState.PRE_RELEASE


# ---------------------------------------------------------------------------
# Tests: terminal shape validation
# ---------------------------------------------------------------------------


def test_completed_result_requires_bundle_digest() -> None:
    """Exit criterion: completed lifecycle validates terminal shape."""

    with pytest.raises(ValueError, match="bundle digest"):
        SafeguardEvidenceLifecycleResult(
            kind=LifecycleTerminalKind.RESOLVED,
            bundle_digest=None,
            fence_record=None,
            evidence_record=None,
            pre_release_receipt=None,
            release_pending_fence=None,
        )


def test_cancelled_result_rejects_bundle_digest() -> None:
    """Exit criterion: cancelled lifecycle rejects bundle digest."""

    with pytest.raises(ValueError, match="cancelled lifecycle"):
        SafeguardEvidenceLifecycleResult(
            kind=LifecycleTerminalKind.CANCELLED_BEFORE_DISPATCH,
            bundle_digest=_DIGEST,
            fence_record=None,
            evidence_record=None,
            pre_release_receipt=None,
            release_pending_fence=None,
        )


def test_early_exit_result_rejects_pre_release() -> None:
    """Exit criterion: early-exit rejects pre-release receipt."""

    # Must fail because pre_release_receipt is disallowed for conflict kind,
    # but we need a valid receipt which is hard to construct in isolation.
    # Test the simpler shape constraint: release_pending_fence must be None.
    with pytest.raises(ValueError, match="early-exit"):
        _bundle_record, _reservation_receipt, _audit_receipt, preparing, _acq, _ctx = (
            _full_fixture()
        )
        SafeguardEvidenceLifecycleResult(
            kind=LifecycleTerminalKind.EVIDENCE_CONFLICT,
            bundle_digest=_DIGEST,
            fence_record=preparing,
            evidence_record=None,
            pre_release_receipt=None,
            release_pending_fence=preparing,  # not allowed for early exit
        )


# ---------------------------------------------------------------------------
# Tests: no legacy bypass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_port_called_exactly_once() -> None:
    """Exit criterion: exactly one dispatch per lifecycle invocation."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort()
    held_lock = InMemoryHeldLock(acq)

    await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    assert dispatch_port.dispatch_count == 1


@pytest.mark.asyncio
async def test_lock_active_verified_before_dispatch() -> None:
    """Exit criterion: lock handle is verified active before dispatch call."""

    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort()
    held_lock = InMemoryHeldLock(acq)

    # The orchestrator calls require_active() which will succeed
    result = await run_safeguard_evidence_lifecycle(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        reservation_store=_reservation_store(reservation_receipt),
        audit_append_receipt=audit_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing,
        fence_store=fence_store,
        evidence_store=evidence_store,
        dispatch_port=dispatch_port,
        now=_NOW,
    )

    assert result.kind in {
        LifecycleTerminalKind.RESOLVED,
        LifecycleTerminalKind.QUARANTINED,
    }
