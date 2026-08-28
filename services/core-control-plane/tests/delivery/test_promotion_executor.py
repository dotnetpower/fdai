from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from fdai.core.measurement import OperationalPromotionReceipt
from fdai.delivery.persistence import StateStoreActionPromotionRegistry
from fdai.delivery.promotion import (
    PROMOTION_ACTION_TYPE,
    OperationalPromotionDirectApiExecutor,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiReceipt,
    DirectApiRequest,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REVISION = "a" * 40
_SCENARIO = "scenario-v1"
_EVIDENCE = "b" * 64


def _action_types():  # type: ignore[no-untyped-def]
    return {
        item.name: item
        for item in load_action_type_catalog(
            _REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=PackageResourceSchemaRegistry(),
        )
    }


def _receipt(action_type) -> OperationalPromotionReceipt:  # type: ignore[no-untyped-def]
    assert action_type.provenance is not None
    return OperationalPromotionReceipt(
        fdai_revision=_REVISION,
        scenario_set_version=_SCENARIO,
        action_type_name=action_type.name,
        action_type_version=action_type.version,
        action_type_digest=action_type.provenance.content_hash.removeprefix("sha256:"),
        evidence_digest=_EVIDENCE,
        observation_days=14.0,
        live_observation_days=14,
        sample_count=100,
        benchmark_samples=50,
        live_shadow_samples=50,
        correct_count=100,
        accuracy=1.0,
        accuracy_ci_lower=0.96,
        accuracy_ci_upper=1.0,
        benchmark_accuracy=1.0,
        benchmark_accuracy_ci_lower=0.92,
        benchmark_accuracy_ci_upper=1.0,
        live_shadow_accuracy=1.0,
        live_shadow_accuracy_ci_lower=0.92,
        live_shadow_accuracy_ci_upper=1.0,
        policy_escapes=0,
        rollback_rate=0.0,
        recurrence_rate=0.0,
        executed_samples=50,
        recurrence_complete_samples=50,
        recurrence_incomplete_samples=0,
        simulation_review_rate=0.0,
        causal_evidence_failures=0,
        ready=True,
        gaps=(),
        decision_evidence_receipt_digest="sha256:" + "d" * 64,
        decision_evidence_verification_bundle_digest="sha256:" + "e" * 64,
    )


class _ReceiptReader:
    def __init__(self, receipt: OperationalPromotionReceipt | None) -> None:
        self.receipt = receipt

    async def load(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return self.receipt


class _ReceiptVerifier:
    def verify(self, *, action_type, receipt):  # type: ignore[no-untyped-def]
        return receipt.action_type_name == action_type.name


class _PersistedAuthorityVerifier:
    async def verify(self, **_kwargs: object) -> bool:
        return True


def _request(target: str, *, mode: Mode) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000010"),
        idempotency_key="promotion-request-1",
        action_type_name=PROMOTION_ACTION_TYPE,
        rule_ids=("operator.request.governance.promote-action-type",),
        resource_ref=f"action-type:{target}",
        arguments={
            "action_type_id": target,
            "target_mode": "enforce",
            "fdai_revision": _REVISION,
            "scenario_set_version": _SCENARIO,
            "evidence_digest": _EVIDENCE,
            "justification": "Measured shadow evidence passed every promotion guard.",
        },
        labels=(mode.value,),
        mode=mode,
    )


async def test_enforce_applies_exact_verified_receipt_and_persists_mode() -> None:
    action_types = _action_types()
    target = action_types["remediate.tag-add"]
    state = InMemoryStateStore()
    registry = StateStoreActionPromotionRegistry(
        store=state,
        receipt_verifier=_ReceiptVerifier(),
        persisted_authority_verifier=_PersistedAuthorityVerifier(),
    )
    executor = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(_receipt(target)),
        registry=registry,
    )

    result = await executor.execute(_request(target.name, mode=Mode.ENFORCE))

    assert result.outcome is DirectApiOutcome.SUCCEEDED
    assert registry.mode_of(target.name) is Mode.ENFORCE
    persisted = await state.read_state(f"action_promotion:{target.name}")
    assert persisted is not None
    assert persisted["mode"] == "enforce"

    replay = await executor.execute(_request(target.name, mode=Mode.ENFORCE))

    assert replay.outcome is DirectApiOutcome.SUCCEEDED
    assert replay.detail == "verified operational promotion receipt already applied"


async def test_restart_replay_cannot_overwrite_newer_persisted_attribution() -> None:
    action_types = _action_types()
    target = action_types["remediate.tag-add"]
    state = InMemoryStateStore()
    newer_receipt = replace(_receipt(target), evidence_digest="c" * 64)
    newer = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(newer_receipt),
        registry=StateStoreActionPromotionRegistry(
            store=state,
            receipt_verifier=_ReceiptVerifier(),
            persisted_authority_verifier=_PersistedAuthorityVerifier(),
        ),
    )
    newer_request = replace(
        _request(target.name, mode=Mode.ENFORCE),
        arguments={
            **_request(target.name, mode=Mode.ENFORCE).arguments,
            "evidence_digest": newer_receipt.evidence_digest,
        },
    )
    await newer.execute(newer_request)

    stale_registry = StateStoreActionPromotionRegistry(
        store=state,
        receipt_verifier=_ReceiptVerifier(),
        persisted_authority_verifier=_PersistedAuthorityVerifier(),
    )
    stale = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(_receipt(target)),
        registry=stale_registry,
    )

    with pytest.raises(DirectApiPreconditionError, match="differs"):
        await stale.execute(_request(target.name, mode=Mode.ENFORCE))

    persisted = await state.read_state(f"action_promotion:{target.name}")
    assert persisted is not None
    assert persisted["promotion_evidence_digest"] == newer_receipt.evidence_digest


async def test_shadow_validates_but_never_changes_promotion_state() -> None:
    action_types = _action_types()
    target = action_types["remediate.tag-add"]
    registry = StateStoreActionPromotionRegistry(
        store=InMemoryStateStore(),
        receipt_verifier=_ReceiptVerifier(),
    )
    executor = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(_receipt(target)),
        registry=registry,
    )

    result = await executor.execute(_request(target.name, mode=Mode.SHADOW))

    assert result.outcome is DirectApiOutcome.SUCCEEDED
    assert registry.record(target.name) is None


async def test_missing_exact_receipt_fails_closed() -> None:
    action_types = _action_types()
    target = action_types["remediate.tag-add"]
    executor = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(None),
        registry=StateStoreActionPromotionRegistry(
            store=InMemoryStateStore(),
            receipt_verifier=_ReceiptVerifier(),
        ),
    )

    with pytest.raises(DirectApiPreconditionError, match="exact operational"):
        await executor.execute(_request(target.name, mode=Mode.ENFORCE))


class _PersistFailureStateStore(InMemoryStateStore):
    """Simulate a durable-write outage after the in-memory record is staged."""

    async def write_state_with_audit_if_absent(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated durable write failure")


async def test_persist_failure_does_not_leave_an_unpersisted_enforce_record() -> None:
    action_types = _action_types()
    target = action_types["remediate.tag-add"]
    registry = StateStoreActionPromotionRegistry(
        store=_PersistFailureStateStore(),
        receipt_verifier=_ReceiptVerifier(),
    )
    executor = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(_receipt(target)),
        registry=registry,
    )

    with pytest.raises(RuntimeError, match="simulated durable write failure"):
        await executor.execute(_request(target.name, mode=Mode.ENFORCE))

    # `consider_promotion` optimistically staged an ENFORCE record before the
    # durable write failed; the executor MUST roll that back so a caller
    # reading the registry never observes a promotion that was never
    # actually persisted.
    assert registry.mode_of(target.name) is Mode.SHADOW
    assert registry.record(target.name) is None


class _ControlledWriteStateStore(InMemoryStateStore):
    """First CAS blocks until released, then fails; the rest succeed."""

    def __init__(self) -> None:
        super().__init__()
        self.write_started = asyncio.Event()
        self.release_write = asyncio.Event()
        self.calls = 0

    async def write_state_with_audit_if_absent(  # type: ignore[no-untyped-def]
        self, key, value, audit_entry
    ):
        self.calls += 1
        if self.calls == 1:
            self.write_started.set()
            await self.release_write.wait()
            raise RuntimeError("simulated durable write failure")
        return await super().write_state_with_audit_if_absent(
            key,
            value,
            audit_entry,
        )


class _ConcurrentCasStateStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self._arrived = 0
        self._both_arrived = asyncio.Event()

    async def write_state_with_audit_if_absent(  # type: ignore[no-untyped-def]
        self, key, value, audit_entry
    ):
        self._arrived += 1
        if self._arrived == 2:
            self._both_arrived.set()
        await self._both_arrived.wait()
        return await super().write_state_with_audit_if_absent(
            key,
            value,
            audit_entry,
        )


async def test_cross_replica_promotions_use_durable_revision_fence() -> None:
    action_types = _action_types()
    target = action_types["remediate.tag-add"]
    store = _ConcurrentCasStateStore()
    receipt_a = _receipt(target)
    receipt_b = replace(receipt_a, evidence_digest="c" * 64)
    executor_a = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(receipt_a),
        registry=StateStoreActionPromotionRegistry(
            store=store,
            receipt_verifier=_ReceiptVerifier(),
        ),
    )
    executor_b = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(receipt_b),
        registry=StateStoreActionPromotionRegistry(
            store=store,
            receipt_verifier=_ReceiptVerifier(),
        ),
    )
    request_a = _request(target.name, mode=Mode.ENFORCE)
    request_b = replace(
        request_a,
        arguments={**request_a.arguments, "evidence_digest": receipt_b.evidence_digest},
    )

    results = await asyncio.gather(
        executor_a.execute(request_a),
        executor_b.execute(request_b),
        return_exceptions=True,
    )

    assert sum(isinstance(result, DirectApiReceipt) for result in results) == 1
    assert (
        sum(
            isinstance(result, RuntimeError) and "authority changed" in str(result)
            for result in results
        )
        == 1
    )
    persisted = await store.read_state(f"action_promotion:{target.name}")
    assert persisted is not None
    assert persisted["revision"] == 1
    assert persisted["promotion_evidence_digest"] in {
        receipt_a.evidence_digest,
        receipt_b.evidence_digest,
    }


async def test_concurrent_failed_promotion_cannot_expose_unpersisted_enforce() -> None:
    """A concurrent attempt for the same ActionType MUST wait for the whole
    read-mutate-persist(-restore) sequence to finish rather than racing it.

    Without the internal per-ActionType lock, a second concurrent call could
    capture the first call's unpersisted ENFORCE mutation as its own "prior"
    state (or clobber the first call's eventual restore), leaving the
    registry in a state that was never actually durable.
    """
    action_types = _action_types()
    target = action_types["remediate.tag-add"]
    store = _ControlledWriteStateStore()
    registry = StateStoreActionPromotionRegistry(
        store=store,
        receipt_verifier=_ReceiptVerifier(),
    )
    executor = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(_receipt(target)),
        registry=registry,
    )
    request = _request(target.name, mode=Mode.ENFORCE)

    task_a = asyncio.create_task(executor.execute(request))
    await store.write_started.wait()

    # A is now inside its critical section, blocked in `persist`. A second
    # concurrent attempt for the same ActionType MUST be unable to start its
    # own `record`/`consider_promotion`/`persist` sequence until A's finishes.
    task_b = asyncio.create_task(executor.execute(request))
    await asyncio.sleep(0)
    assert not task_b.done()
    assert executor._locks.snapshot().get(target.name) is True

    store.release_write.set()
    with pytest.raises(RuntimeError, match="simulated durable write failure"):
        await task_a

    # Only after A's failure was fully rolled back does B get to run; its
    # own attempt observes the correctly-restored prior state and durably
    # persists its own ENFORCE promotion.
    result_b = await task_b
    assert result_b.outcome is DirectApiOutcome.SUCCEEDED
    assert registry.mode_of(target.name) is Mode.ENFORCE
    persisted = await store.read_state(f"action_promotion:{target.name}")
    assert persisted is not None
    assert persisted["mode"] == "enforce"
    assert store.calls == 2


async def test_mismatched_receipt_identity_fails_closed() -> None:
    action_types = _action_types()
    target = action_types["remediate.tag-add"]
    mismatched = replace(_receipt(target), evidence_digest="c" * 64)
    executor = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(mismatched),
        registry=StateStoreActionPromotionRegistry(
            store=InMemoryStateStore(),
            receipt_verifier=_ReceiptVerifier(),
        ),
    )

    with pytest.raises(DirectApiPreconditionError, match="identity mismatched"):
        await executor.execute(_request(target.name, mode=Mode.ENFORCE))


async def test_legacy_receipt_without_decision_evidence_fails_closed() -> None:
    action_types = _action_types()
    target = action_types["remediate.tag-add"]
    legacy = replace(
        _receipt(target),
        decision_evidence_receipt_digest=None,
        decision_evidence_verification_bundle_digest=None,
    )
    executor = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=_ReceiptReader(legacy),
        registry=StateStoreActionPromotionRegistry(
            store=InMemoryStateStore(),
            receipt_verifier=_ReceiptVerifier(),
        ),
    )

    with pytest.raises(DirectApiPreconditionError, match="lacks independent"):
        await executor.execute(_request(target.name, mode=Mode.ENFORCE))
