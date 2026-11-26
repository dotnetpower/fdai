"""Safeguard evidence lifecycle orchestrator contract tests.

Covers #681 exit criteria: complete order, every failure boundary,
cancellation, crash/restart recovery, duplicate delivery, target
contention, and no legacy bypass.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.executor.audit_intent import AuditIntentAppendReceipt
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationTransitionReceipt,
    begin_dispatch,
)
from fdai.core.executor.safeguard_bundle_context import SafeguardBundlePersistenceContext
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
    DispatchBoundaryGuard,
    DispatchNotAttemptedError,
    LifecycleTerminalKind,
    SafeguardEvidenceLifecycleResult,
    _await_after_dispatch,
    cancel_before_dispatch,
    run_safeguard_evidence_lifecycle,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
    TargetDispatchFenceTransitionReceipt,
    attach_prepared_evidence,
)
from fdai.core.executor.testing_safeguard_lifecycle import InMemoryIdempotencyReservationStore
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    LockOwnershipRejectionReason,
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseReceipt,
    ResourceLockReleaseState,
)
from fdai_service_contracts.ontology_query import content_digest

from tests.core.executor.test_safeguard_dispatch_checkpoint import _evidence_fixture

_NOW = datetime(2026, 9, 10, 13, 0, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64
_SOURCE_REVISION = "commit:" + "b" * 40


class InMemoryFenceStore:
    def __init__(self) -> None:
        self._records: dict[str, TargetDispatchFenceRecord] = {}
        self._call_log: list[str] = []

    async def acquire_generation(self, record: TargetDispatchFenceRecord) -> object:
        raise NotImplementedError

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceTransitionReceipt:
        self._call_log.append("compare_and_transition")
        existing = self._records[record.identity.target_digest]
        assert existing.record_digest == prior_record_digest
        assert existing.revision == expected_revision
        self._records[record.identity.target_digest] = record
        return TargetDispatchFenceTransitionReceipt.create(
            prior_record=existing,
            record=record,
            store_receipt_digest=_make_digest("fence-cas"),
            recorded_at=record.state_changed_at,
        )

    async def read(self, target_digest: str) -> TargetDispatchFenceRecord | None:
        self._call_log.append("read")
        return self._records.get(target_digest)


class InMemoryEvidenceStore:
    def __init__(
        self,
        *,
        delay_bundle: bool = False,
        delay_dispatch_start: bool = False,
    ) -> None:
        self._records: dict[tuple[str, int], SafeguardDispatchEvidenceRecord] = {}
        self._call_log: list[str] = []
        self._delay_bundle = delay_bundle
        self._delay_dispatch_start = delay_dispatch_start

    async def persist_bundle(
        self, record: SafeguardDispatchEvidenceRecord
    ) -> SafeguardDispatchPersistenceResult:
        self._call_log.append("persist_bundle")
        key = (record.identity.target_digest, record.identity.target_fence_generation)
        existing = self._records.get(key)
        if existing is None:
            self._records[key] = record
            ts = record.state_changed_at + (
                timedelta(microseconds=1) if self._delay_bundle else timedelta()
            )
            receipt = SafeguardDispatchTransitionReceipt.create(
                prior_record=None,
                record=record,
                store_receipt_digest=_make_digest("evidence-persist"),
                recorded_at=ts,
            )
            return SafeguardDispatchPersistenceResult(
                candidate_identity=record.identity,
                decision=SafeguardDispatchPersistenceDecision.PERSISTED,
                observed_record=record,
                transition_receipt=receipt,
            )
        return SafeguardDispatchPersistenceResult(
            candidate_identity=record.identity,
            decision=classify_safeguard_dispatch_evidence(existing, record.identity),
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
        existing = self._records[key]
        assert existing.record_digest == prior_record_digest
        assert existing.revision == expected_revision
        self._records[key] = record
        ts = (
            _NOW + timedelta(seconds=4)
            if self._delay_dispatch_start
            and record.state is SafeguardDispatchEvidenceState.DISPATCH_STARTED
            else record.state_changed_at
        )
        return SafeguardDispatchTransitionReceipt.create(
            prior_record=existing,
            record=record,
            bundle_persistence_receipt=bundle_persistence_receipt,
            current_lock_assessment=current_lock_assessment,
            store_receipt_digest=_make_digest("evidence-cas"),
            recorded_at=ts,
        )

    async def read(
        self, target_digest: str, generation: int
    ) -> SafeguardDispatchEvidenceRecord | None:
        self._call_log.append("read")
        return self._records.get((target_digest, generation))


class InMemoryDispatchPort:
    def __init__(
        self,
        *,
        transport: DispatchTransportState = DispatchTransportState.ACKNOWLEDGED,
        sink: AuthoritativeSinkState = AuthoritativeSinkState.ACCEPTED,
        call_guard: bool = True,
        before_guard_exc: BaseException | None = None,
        after_guard_exc: BaseException | None = None,
    ) -> None:
        self.transport = transport
        self.sink = sink
        self.call_guard = call_guard
        self.before_guard_exc = before_guard_exc
        self.after_guard_exc = after_guard_exc
        self.dispatch_count = 0
        self.last_evidence: SafeguardDispatchEvidenceRecord | None = None

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
        pre_invoke_guard: DispatchBoundaryGuard,
    ) -> tuple[DispatchTransportState, AuthoritativeSinkState, str | None, str | None]:
        if self.before_guard_exc is not None:
            raise self.before_guard_exc
        if self.call_guard:
            await pre_invoke_guard()
        if self.after_guard_exc is not None:
            raise self.after_guard_exc
        self.dispatch_count += 1
        self.last_evidence = evidence_record
        accepted = self.sink in {
            AuthoritativeSinkState.ACCEPTED,
            AuthoritativeSinkState.COMMITTED,
        }
        known = self.sink not in {
            AuthoritativeSinkState.UNOBSERVED,
            AuthoritativeSinkState.UNKNOWN,
        }
        return (
            self.transport,
            self.sink,
            _DIGEST if accepted else None,
            _DIGEST if known else None,
        )


class InMemoryHeldLock:
    def __init__(
        self,
        receipt: ResourceLockAcquisitionReceipt,
        *,
        active: bool = True,
        owner: bool = True,
        ownership_sequence: tuple[bool, ...] | None = None,
        verifier_id: str = "postgres-pg-locks-readback",
        verifier_version: str = "1.0.0",
        trust_anchor_id: str = "postgres:primary",
        second_assess_exc: BaseException | None = None,
    ) -> None:
        self._receipt = receipt
        self._active = active
        self._owner = owner
        self._ownership_sequence = ownership_sequence
        self._assessment_count = 0
        self._verifier_id = verifier_id
        self._verifier_version = verifier_version
        self._trust_anchor_id = trust_anchor_id
        self._second_assess_exc = second_assess_exc
        self._request = ResourceLockAcquisitionRequest.create(
            target_ref="resource/example",
            action_digest=receipt.action_digest,
            attempt=receipt.attempt,
            producer_id=receipt.producer_id,
            producer_version=receipt.producer_version,
            source_revision=_SOURCE_REVISION,
        )

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
        self._assessment_count += 1
        if self._assessment_count >= 2 and self._second_assess_exc is not None:
            raise self._second_assess_exc
        owner = self._owner
        if self._ownership_sequence is not None:
            idx = min(self._assessment_count - 1, len(self._ownership_sequence) - 1)
            owner = self._ownership_sequence[idx]
        return LiveLockOwnershipAssessment.create(
            self._receipt,
            current_fencing_generation=None,
            current_session_identity=self._receipt.session_identity if owner else None,
            verifier_id=self._verifier_id,
            verifier_version=self._verifier_version,
            trust_anchor_id=self._trust_anchor_id,
            provider_attestation_digest=_make_digest("ownership-attest"),
            evaluated_at=_NOW + timedelta(seconds=2),
            valid_until=_NOW + timedelta(seconds=5),
            rejection_reasons=() if owner else (LockOwnershipRejectionReason.LOCK_LOST,),
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


def _make_digest(domain: str) -> str:
    return content_digest({"domain": domain, "ts": _NOW.isoformat()})


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
    idempotency_key: str = "example-idem",
) -> tuple[
    SafeguardDispatchEvidenceRecord,
    IdempotencyReservationTransitionReceipt,
    AuditIntentAppendReceipt,
    TargetDispatchFenceRecord,
    ResourceLockAcquisitionReceipt,
    SafeguardBundlePersistenceContext,
]:
    bundle_record, _res_id, preparing, _prepared, ctx = _evidence_fixture(
        now=now,
        target_ref=target_ref,
        idempotency_key=idempotency_key,
    )
    return (
        bundle_record,
        ctx.reservation_receipt,
        ctx.audit_append_receipt,
        preparing,
        ctx.lock_assessment.acquisition_receipt,
        ctx,
    )


async def _run_lifecycle(
    *,
    held_lock: InMemoryHeldLock | None = None,
    reservation_receipt: IdempotencyReservationTransitionReceipt | None = None,
    audit_append_receipt: AuditIntentAppendReceipt | None = None,
    bundle_record: SafeguardDispatchEvidenceRecord | None = None,
    preparing_fence: TargetDispatchFenceRecord | None = None,
    fence_store: InMemoryFenceStore | None = None,
    evidence_store: InMemoryEvidenceStore | None = None,
    dispatch_port: InMemoryDispatchPort | None = None,
    clock: object = None,
) -> SafeguardEvidenceLifecycleResult:
    b_rec, res_rec, aud_rec, prep, acq, _ctx = _full_fixture()
    res = reservation_receipt or res_rec
    prep_fence = preparing_fence or prep
    f_store = fence_store or InMemoryFenceStore()
    if prep_fence.identity.target_digest not in f_store._records:
        f_store._records[prep_fence.identity.target_digest] = prep_fence
    return await run_safeguard_evidence_lifecycle(
        held_lock=held_lock or InMemoryHeldLock(acq),
        reservation_receipt=res,
        reservation_store=_reservation_store(res),
        audit_append_receipt=audit_append_receipt or aud_rec,
        bundle_record=bundle_record or b_rec,
        preparing_fence=prep_fence,
        fence_store=f_store,
        evidence_store=evidence_store or InMemoryEvidenceStore(),
        dispatch_port=dispatch_port or InMemoryDispatchPort(),
        now=_NOW,
        clock=clock,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_lifecycle_completes_resolved_with_exact_order() -> None:
    bundle_record, *_ = _full_fixture()
    dispatch_port = InMemoryDispatchPort()
    result = await _run_lifecycle(dispatch_port=dispatch_port)

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
async def test_lifecycle_records_fresh_post_dispatch_times() -> None:
    dispatch_port = InMemoryDispatchPort()
    readings = iter(
        [*([_NOW] * 5), _NOW + timedelta(seconds=3), *([_NOW + timedelta(seconds=4)] * 2)]
    )
    read_count = 0

    def post_dispatch_clock() -> datetime:
        nonlocal read_count
        read_count += 1
        if read_count > 5:
            assert dispatch_port.dispatch_count == 1
        return next(readings)

    result = await _run_lifecycle(dispatch_port=dispatch_port, clock=post_dispatch_clock)
    assert result.evidence_record is not None
    assert result.evidence_record.dispatch_observation is not None
    assert result.evidence_record.dispatch_observation.observed_at == _NOW + timedelta(seconds=3)
    assert result.evidence_record.pre_release_checkpoint is not None
    assert result.evidence_record.pre_release_checkpoint.observed_at == _NOW + timedelta(seconds=4)
    assert result.release_pending_fence is not None
    assert result.release_pending_fence.state_changed_at == _NOW + timedelta(seconds=4)


@pytest.mark.asyncio
async def test_lifecycle_orders_dispatch_after_authoritative_store_time() -> None:
    dispatch_port = InMemoryDispatchPort()
    result = await _run_lifecycle(
        evidence_store=InMemoryEvidenceStore(delay_bundle=True),
        dispatch_port=dispatch_port,
        clock=lambda: _NOW + timedelta(seconds=2),
    )
    assert result.kind is LifecycleTerminalKind.RESOLVED
    assert dispatch_port.last_evidence is not None
    assert dispatch_port.last_evidence.dispatch_start_checkpoint is not None
    assert (
        dispatch_port.last_evidence.dispatch_start_checkpoint.dispatch_started_at
        == _NOW + timedelta(seconds=2)
    )


@pytest.mark.asyncio
async def test_lifecycle_rejects_expired_pre_dispatch_ownership() -> None:
    dispatch_port = InMemoryDispatchPort()
    result = await _run_lifecycle(
        evidence_store=InMemoryEvidenceStore(delay_dispatch_start=True),
        dispatch_port=dispatch_port,
        clock=lambda: _NOW + timedelta(seconds=2),
    )
    assert dispatch_port.dispatch_count == 0
    assert result.kind is LifecycleTerminalKind.QUARANTINED
    assert result.dispatch_performed is False
    assert result.reason == "dispatch blocked before provider invocation: ValueError"


@pytest.mark.asyncio
async def test_lifecycle_quarantines_on_unknown_sink_failed_transport_or_lost_lock() -> None:
    unknown_sink = await _run_lifecycle(
        dispatch_port=InMemoryDispatchPort(
            transport=DispatchTransportState.ACKNOWLEDGED,
            sink=AuthoritativeSinkState.UNKNOWN,
        )
    )
    assert unknown_sink.kind is LifecycleTerminalKind.QUARANTINED

    failed_tx = await _run_lifecycle(
        dispatch_port=InMemoryDispatchPort(
            transport=DispatchTransportState.FAILED,
            sink=AuthoritativeSinkState.UNOBSERVED,
        )
    )
    assert failed_tx.kind is LifecycleTerminalKind.QUARANTINED

    *_, acq, _ctx = _full_fixture()
    lost_lock = await _run_lifecycle(
        held_lock=InMemoryHeldLock(acq, ownership_sequence=(True, False))
    )
    assert lost_lock.kind is LifecycleTerminalKind.QUARANTINED


@pytest.mark.asyncio
async def test_evidence_conflict_stops_before_dispatch() -> None:
    bundle_record, *_ = _full_fixture()
    evidence_store = InMemoryEvidenceStore()
    dispatch_port = InMemoryDispatchPort()
    key = (bundle_record.identity.target_digest, bundle_record.identity.target_fence_generation)

    evidence_store._records[key] = bundle_record
    dup_result = await _run_lifecycle(evidence_store=evidence_store, dispatch_port=dispatch_port)
    assert dup_result.kind is LifecycleTerminalKind.EVIDENCE_CONFLICT

    other_bundle, *_ = _full_fixture(idempotency_key="other-idem")
    evidence_store._records[key] = other_bundle
    conflict_result = await _run_lifecycle(
        evidence_store=evidence_store, dispatch_port=dispatch_port
    )
    assert conflict_result.kind is LifecycleTerminalKind.EVIDENCE_CONFLICT
    assert dispatch_port.dispatch_count == 0


@pytest.mark.asyncio
async def test_cancel_before_dispatch_and_inactive_lock() -> None:
    _b, _r, _a, preparing, acq, _ctx = _full_fixture()
    fence_store = InMemoryFenceStore()
    fence_store._records[preparing.identity.target_digest] = preparing

    result = await cancel_before_dispatch(
        held_lock=InMemoryHeldLock(acq),
        preparing_fence=preparing,
        no_dispatch_evidence_digest=_DIGEST,
        fence_store=fence_store,
        now=_NOW,
    )
    assert result.kind is LifecycleTerminalKind.CANCELLED_BEFORE_DISPATCH
    assert result.bundle_digest is None
    assert result.fence_record is not None
    assert result.fence_record.state is TargetDispatchFenceState.RESOLVED

    with pytest.raises(RuntimeError, match="lock is no longer active"):
        await cancel_before_dispatch(
            held_lock=InMemoryHeldLock(acq, active=False),
            preparing_fence=preparing,
            no_dispatch_evidence_digest=_DIGEST,
            fence_store=fence_store,
            now=_NOW,
        )


@pytest.mark.asyncio
async def test_rejects_invalid_prior_states_and_inactive_lock() -> None:
    bundle_record, reservation_receipt, audit_receipt, preparing, acq, _ctx = _full_fixture()
    in_flight = begin_dispatch(reservation_receipt.record, at=_NOW)
    bad_receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=reservation_receipt.record,
        record=in_flight,
        expected_prior_revision=reservation_receipt.record.revision,
        store_receipt_digest=_make_digest("bad-reservation"),
        recorded_at=_NOW,
    )
    with pytest.raises(ValueError, match="current reserved"):
        await _run_lifecycle(reservation_receipt=bad_receipt)

    prepared = attach_prepared_evidence(
        preparing,
        audit_append_receipt=audit_receipt,
        safeguard_bundle_digest=bundle_record.bundle.bundle_digest,
        changed_at=_NOW,
    )
    with pytest.raises(ValueError, match="preparing target fence"):
        await _run_lifecycle(preparing_fence=prepared)

    with pytest.raises(RuntimeError, match="lock is no longer active"):
        await _run_lifecycle(held_lock=InMemoryHeldLock(acq, active=False))


def test_result_rejects_execution_and_verification_authority() -> None:
    for kwargs in (
        {"execution_authority": True, "effect_verification_authority": False},
        {"execution_authority": False, "effect_verification_authority": True},
    ):
        with pytest.raises(ValueError, match="MUST NOT grant authority"):
            SafeguardEvidenceLifecycleResult(
                kind=LifecycleTerminalKind.FENCE_BLOCKED,
                bundle_digest=None,
                fence_record=None,
                evidence_record=None,
                pre_release_receipt=None,
                release_pending_fence=None,
                **kwargs,  # type: ignore[arg-type]
            )
    with pytest.raises(ValueError, match="kind is invalid"):
        SafeguardEvidenceLifecycleResult(
            kind="bad",  # type: ignore[arg-type]
            bundle_digest=None,
            fence_record=None,
            evidence_record=None,
            pre_release_receipt=None,
            release_pending_fence=None,
        )


@pytest.mark.asyncio
async def test_dispatch_evidence_separates_transport_from_sink_and_commits() -> None:
    bundle_record, _res, _aud, preparing, _acq, _ctx = _full_fixture()
    result = await _run_lifecycle(
        dispatch_port=InMemoryDispatchPort(
            transport=DispatchTransportState.SENT,
            sink=AuthoritativeSinkState.UNOBSERVED,
        )
    )
    assert result.kind is LifecycleTerminalKind.QUARANTINED
    assert result.evidence_record is not None
    assert result.evidence_record.independent_effect_state == "pending"

    fence_store2 = InMemoryFenceStore()
    evidence_store2 = InMemoryEvidenceStore()
    dispatch_port2 = InMemoryDispatchPort(
        transport=DispatchTransportState.ACKNOWLEDGED,
        sink=AuthoritativeSinkState.COMMITTED,
    )
    resolved = await _run_lifecycle(
        fence_store=fence_store2,
        evidence_store=evidence_store2,
        dispatch_port=dispatch_port2,
    )
    assert resolved.kind is LifecycleTerminalKind.RESOLVED
    assert dispatch_port2.dispatch_count == 1
    assert evidence_store2._call_log.count("persist_bundle") == 1
    assert evidence_store2._call_log.count("compare_and_transition") == 3
    assert await fence_store2.read(preparing.identity.target_digest) is not None
    assert (
        await evidence_store2.read(
            bundle_record.identity.target_digest,
            bundle_record.identity.target_fence_generation,
        )
        is not None
    )


def test_terminal_shape_validation_branches() -> None:
    bundle_record, _res, _aud, preparing, _acq, _ctx = _full_fixture()
    ev_rcpt = SafeguardDispatchTransitionReceipt.create(
        prior_record=None,
        record=bundle_record,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )
    fn_rcpt = TargetDispatchFenceTransitionReceipt.create(
        prior_record=None,
        record=preparing,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )
    base: dict[str, object] = {
        "kind": LifecycleTerminalKind.RESOLVED,
        "bundle_digest": _DIGEST,
        "fence_record": preparing,
        "evidence_record": bundle_record,
        "pre_release_receipt": ev_rcpt,
        "release_pending_fence": preparing,
        "release_pending_receipt": fn_rcpt,
    }
    early: dict[str, object] = {
        "kind": LifecycleTerminalKind.EVIDENCE_CONFLICT,
        "bundle_digest": _DIGEST,
        "fence_record": preparing,
        "evidence_record": None,
        "pre_release_receipt": None,
        "release_pending_fence": None,
        "release_pending_receipt": None,
    }
    cancelled: dict[str, object] = {
        **early,
        "kind": LifecycleTerminalKind.CANCELLED_BEFORE_DISPATCH,
        "bundle_digest": None,
    }
    for overrides, match in (
        ({**base, "bundle_digest": None}, "bundle digest"),
        ({**base, "fence_record": None}, "terminal records"),
        ({**base, "pre_release_receipt": None}, "pre-release receipt"),
        ({**base, "release_pending_fence": None}, "release-pending fence"),
        ({**base, "release_pending_receipt": None}, "release-pending receipt"),
        ({**cancelled, "bundle_digest": _DIGEST}, "MUST NOT have bundle digest"),
        ({**cancelled, "fence_record": None}, "requires resolved fence"),
        ({**early, "pre_release_receipt": ev_rcpt}, "MUST NOT have pre-release receipt"),
        ({**early, "release_pending_fence": preparing}, "MUST NOT have release-pending fence"),
        ({**early, "release_pending_receipt": fn_rcpt}, "MUST NOT have release-pending receipt"),
    ):
        with pytest.raises(ValueError, match=match):
            SafeguardEvidenceLifecycleResult(**overrides)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_prior_phase_and_pre_dispatch_failure_branches() -> None:
    _other_bundle, _other_res, other_audit, other_prep, _other_acq, _ = _full_fixture(
        idempotency_key="other-idem"
    )
    with pytest.raises(ValueError, match="audit intent changed reservation identity"):
        await _run_lifecycle(audit_append_receipt=other_audit)

    with pytest.raises(ValueError, match="fence changed reservation identity"):
        await _run_lifecycle(preparing_fence=other_prep)

    bad_state_bundle, *_ = _full_fixture()
    object.__setattr__(bad_state_bundle, "state", SafeguardDispatchEvidenceState.DISPATCH_STARTED)
    with pytest.raises(ValueError, match="bundle-persisted evidence state"):
        await _run_lifecycle(bundle_record=bad_state_bundle)

    bad_auth_bundle, *_ = _full_fixture()
    object.__setattr__(bad_auth_bundle, "execution_authority", True)
    with pytest.raises(ValueError, match="bundle MUST NOT grant authority"):
        await _run_lifecycle(bundle_record=bad_auth_bundle)

    class _NoReceiptStore(InMemoryEvidenceStore):
        async def persist_bundle(
            self, record: SafeguardDispatchEvidenceRecord
        ) -> SafeguardDispatchPersistenceResult:
            res = await super().persist_bundle(record)
            object.__setattr__(res, "transition_receipt", None)
            return res

    with pytest.raises(ValueError, match="persisted bundle lacks receipt"):
        await _run_lifecycle(evidence_store=_NoReceiptStore())


@pytest.mark.asyncio
async def test_dispatch_and_post_dispatch_exception_and_cancellation_branches() -> None:
    *_, acq, _ctx = _full_fixture()

    not_attempted = await _run_lifecycle(
        dispatch_port=InMemoryDispatchPort(before_guard_exc=DispatchNotAttemptedError("not sent"))
    )
    assert not_attempted.kind is LifecycleTerminalKind.QUARANTINED
    assert not_attempted.reason == "dispatch transport proved no publication"

    cancelled_pre = await _run_lifecycle(
        dispatch_port=InMemoryDispatchPort(before_guard_exc=asyncio.CancelledError())
    )
    assert cancelled_pre.kind is LifecycleTerminalKind.QUARANTINED
    assert cancelled_pre.cancellation_requested is True

    skipped_guard = await _run_lifecycle(dispatch_port=InMemoryDispatchPort(call_guard=False))
    assert skipped_guard.kind is LifecycleTerminalKind.QUARANTINED
    assert skipped_guard.reason == "dispatch blocked before provider invocation"

    changed_verifier = await _run_lifecycle(
        held_lock=InMemoryHeldLock(acq, verifier_id="other-verifier")
    )
    assert changed_verifier.kind is LifecycleTerminalKind.QUARANTINED

    with pytest.raises(asyncio.CancelledError):
        await _run_lifecycle(
            dispatch_port=InMemoryDispatchPort(after_guard_exc=asyncio.CancelledError())
        )

    with pytest.raises(RuntimeError, match="post-guard boom"):
        await _run_lifecycle(
            dispatch_port=InMemoryDispatchPort(after_guard_exc=RuntimeError("post-guard boom"))
        )

    assess_cancelled = await _run_lifecycle(
        held_lock=InMemoryHeldLock(acq, second_assess_exc=asyncio.CancelledError())
    )
    assert assess_cancelled.kind is LifecycleTerminalKind.QUARANTINED
    assert assess_cancelled.cancellation_requested is True

    assess_failed = await _run_lifecycle(
        held_lock=InMemoryHeldLock(acq, second_assess_exc=RuntimeError("verifier failed"))
    )
    assert assess_failed.kind is LifecycleTerminalKind.QUARANTINED
    assert assess_failed.reason == "pre-release ownership assessment failed"


@pytest.mark.asyncio
async def test_await_after_dispatch_shield_and_cancellation_branches() -> None:
    loop = asyncio.get_running_loop()
    fut1: asyncio.Future[str] = loop.create_future()
    task = asyncio.create_task(_await_after_dispatch(fut1))
    await asyncio.sleep(0)
    task.cancel()
    fut1.set_result("done")
    value, was_cancelled = await task
    assert value == "done" and was_cancelled is True

    fut2: asyncio.Future[str] = loop.create_future()
    task2 = asyncio.create_task(_await_after_dispatch(fut2))
    await asyncio.sleep(0)
    task2.cancel()
    fut2.set_exception(RuntimeError("write failed"))
    with pytest.raises(asyncio.CancelledError):
        await task2

    fut3: asyncio.Future[str] = loop.create_future()
    fut3.set_exception(RuntimeError("direct failure"))
    with pytest.raises(RuntimeError, match="direct failure"):
        await _await_after_dispatch(fut3)

    cancelled_inner: asyncio.Future[str] = loop.create_future()
    cancelled_inner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await _await_after_dispatch(cancelled_inner)
