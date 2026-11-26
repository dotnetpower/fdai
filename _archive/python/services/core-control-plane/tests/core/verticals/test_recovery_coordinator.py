"""Durable recovery-plan CAS, approval, replay, and corruption invariants."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.verticals.resilience.recovery_coordinator import (
    RecoveryApprovalError,
    RecoveryCoordinatorError,
    RecoveryPlanCoordinator,
    RecoveryRecordError,
    RecoveryWriteConflictError,
)
from fdai.core.verticals.resilience.recovery_plan import (
    RecoveryMode,
    RecoveryObjectives,
    RecoveryPlan,
    RecoveryProfile,
    RecoveryState,
)
from fdai.shared.providers.control_plane_recovery import RecoveryApprovalEvidence
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_AT = datetime(2026, 7, 31, tzinfo=UTC)


class _ApprovalVerifier:
    def __init__(self, *, verified: bool = True, error: Exception | None = None) -> None:
        self.verified = verified
        self.error = error
        self.seen: list[RecoveryApprovalEvidence] = []

    async def verify(self, evidence: RecoveryApprovalEvidence) -> bool:
        self.seen.append(evidence)
        if self.error is not None:
            raise self.error
        return self.verified


def _plan(*, plan_id: str = "regional-recovery") -> RecoveryPlan:
    return RecoveryPlan(
        plan_id=plan_id,
        revision=1,
        mode=RecoveryMode.DRILL,
        profile=RecoveryProfile.RESTORE,
        primary_region="primary-region",
        recovery_region="recovery-region",
        requester_ref="group:requesters",
        scope=("control-plane", "state-store"),
        objectives=RecoveryObjectives(3600, 7200, 10800),
        stop_conditions=("fence_unverified",),
        rollback_ref="runbook://control-plane-failover",
        max_affected_resources=4,
    )


async def _created(
    *,
    verifier: _ApprovalVerifier | None = None,
    store: InMemoryStateStore | None = None,
) -> tuple[RecoveryPlanCoordinator, InMemoryStateStore]:
    state_store = store or InMemoryStateStore()
    coordinator = RecoveryPlanCoordinator(
        state_store=state_store,
        approval_verifier=verifier,
    )
    await coordinator.create(
        _plan(),
        actor_ref="group:operations",
        at=_AT,
        evidence_refs=("evidence://plan/review",),
    )
    return coordinator, state_store


async def test_create_is_atomic_idempotent_and_audited() -> None:
    coordinator, store = await _created()
    repeated = await coordinator.create(
        _plan(),
        actor_ref="group:operations",
        at=_AT,
        evidence_refs=("evidence://plan/review",),
    )
    assert repeated.storage_revision == 0
    assert repeated.plan.state is RecoveryState.DRAFT
    assert len(list(store.audit_entries)) == 1
    assert await store.verify_chain()


async def test_conflicting_create_is_rejected() -> None:
    coordinator, _ = await _created()
    with pytest.raises(RecoveryWriteConflictError, match="already exists"):
        await coordinator.create(
            replace(_plan(), recovery_region="another-region"),
            actor_ref="group:operations",
            at=_AT,
            evidence_refs=("evidence://plan/other",),
        )


async def test_transition_persists_state_and_audit_atomically() -> None:
    coordinator, store = await _created()
    ready = await coordinator.transition(
        plan_id="regional-recovery",
        expected_storage_revision=0,
        expected_state=RecoveryState.DRAFT,
        target=RecoveryState.READY,
        actor_ref="group:operations",
        at=_AT + timedelta(seconds=1),
        evidence_refs=("evidence://readiness/pass",),
    )
    assert ready.storage_revision == 1
    assert ready.plan.state is RecoveryState.READY
    entry = list(store.audit_entries)[-1]["entry"]
    assert entry["from_state"] == "draft"
    assert entry["to_state"] == "ready"
    assert entry["idempotency_key"] == ready.last_idempotency_key


async def test_stale_revision_and_state_are_rejected() -> None:
    coordinator, _ = await _created()
    await coordinator.transition(
        plan_id="regional-recovery",
        expected_storage_revision=0,
        expected_state=RecoveryState.DRAFT,
        target=RecoveryState.READY,
        actor_ref="group:operations",
        at=_AT + timedelta(seconds=1),
        evidence_refs=("evidence://ready",),
    )
    with pytest.raises(RecoveryWriteConflictError, match="revision"):
        await coordinator.transition(
            plan_id="regional-recovery",
            expected_storage_revision=0,
            expected_state=RecoveryState.DRAFT,
            target=RecoveryState.READY,
            actor_ref="group:stale-writer",
            at=_AT + timedelta(seconds=1),
            evidence_refs=("evidence://ready/stale",),
        )
    with pytest.raises(RecoveryWriteConflictError, match="state conflict"):
        await coordinator.transition(
            plan_id="regional-recovery",
            expected_storage_revision=1,
            expected_state=RecoveryState.DRAFT,
            target=RecoveryState.APPROVED,
            actor_ref="group:approvers",
            at=_AT + timedelta(seconds=2),
            evidence_refs=("evidence://approval",),
            approval_ref="approval://one",
        )


async def test_approval_is_action_bound_and_required() -> None:
    verifier = _ApprovalVerifier()
    coordinator, _ = await _created(verifier=verifier)
    ready = await coordinator.transition(
        plan_id="regional-recovery",
        expected_storage_revision=0,
        expected_state=RecoveryState.DRAFT,
        target=RecoveryState.READY,
        actor_ref="group:operations",
        at=_AT + timedelta(seconds=1),
        evidence_refs=("evidence://ready",),
    )
    approved = await coordinator.transition(
        plan_id="regional-recovery",
        expected_storage_revision=ready.storage_revision,
        expected_state=RecoveryState.READY,
        target=RecoveryState.APPROVED,
        actor_ref="group:approvers",
        at=_AT + timedelta(seconds=2),
        evidence_refs=("evidence://approval",),
        approval_ref="approval://one",
    )
    assert approved.plan.state is RecoveryState.APPROVED
    assert verifier.seen == [
        RecoveryApprovalEvidence(
            approval_ref="approval://one",
            actor_ref="group:approvers",
            plan_id="regional-recovery",
            plan_revision=1,
            target_state="approved",
        )
    ]


@pytest.mark.parametrize(
    "verifier",
    [None, _ApprovalVerifier(verified=False), _ApprovalVerifier(error=RuntimeError("down"))],
)
async def test_missing_rejected_or_failed_approval_fails_closed(
    verifier: _ApprovalVerifier | None,
) -> None:
    coordinator, _ = await _created(verifier=verifier)
    await coordinator.transition(
        plan_id="regional-recovery",
        expected_storage_revision=0,
        expected_state=RecoveryState.DRAFT,
        target=RecoveryState.READY,
        actor_ref="group:operations",
        at=_AT + timedelta(seconds=1),
        evidence_refs=("evidence://ready",),
    )
    with pytest.raises(RecoveryApprovalError):
        await coordinator.transition(
            plan_id="regional-recovery",
            expected_storage_revision=1,
            expected_state=RecoveryState.READY,
            target=RecoveryState.APPROVED,
            actor_ref="group:approvers",
            at=_AT + timedelta(seconds=2),
            evidence_refs=("evidence://approval",),
            approval_ref="approval://one",
        )


async def test_transition_time_cannot_move_backwards() -> None:
    coordinator, _ = await _created()
    with pytest.raises(RecoveryWriteConflictError, match="timestamp"):
        await coordinator.transition(
            plan_id="regional-recovery",
            expected_storage_revision=0,
            expected_state=RecoveryState.DRAFT,
            target=RecoveryState.READY,
            actor_ref="group:operations",
            at=_AT - timedelta(seconds=1),
            evidence_refs=("evidence://ready",),
        )


async def test_naive_timestamps_fail_closed() -> None:
    coordinator = RecoveryPlanCoordinator(state_store=InMemoryStateStore())
    with pytest.raises(RecoveryCoordinatorError, match="timezone-aware"):
        await coordinator.create(
            _plan(),
            actor_ref="group:operations",
            at=datetime(2026, 7, 31),
            evidence_refs=("evidence://plan",),
        )


async def test_concurrent_transition_has_one_cas_winner() -> None:
    coordinator, store = await _created()

    async def advance(actor: str) -> object:
        return await coordinator.transition(
            plan_id="regional-recovery",
            expected_storage_revision=0,
            expected_state=RecoveryState.DRAFT,
            target=RecoveryState.READY,
            actor_ref=actor,
            at=_AT + timedelta(seconds=1),
            evidence_refs=(f"evidence://ready/{actor}",),
        )

    results = await asyncio.gather(
        advance("group:a"),
        advance("group:b"),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, RecoveryWriteConflictError) for result in results) == 1
    assert len(list(store.audit_entries)) == 2


async def test_same_transition_redelivery_returns_cas_winner() -> None:
    coordinator, _ = await _created()

    async def advance() -> object:
        return await coordinator.transition(
            plan_id="regional-recovery",
            expected_storage_revision=0,
            expected_state=RecoveryState.DRAFT,
            target=RecoveryState.READY,
            actor_ref="group:operations",
            at=_AT + timedelta(seconds=1),
            evidence_refs=("evidence://ready",),
        )

    first, second = await asyncio.gather(
        advance(),
        advance(),
        return_exceptions=True,
    )
    assert not isinstance(first, Exception)
    assert not isinstance(second, Exception)
    assert first == second


async def test_redelivery_with_changed_evidence_is_a_conflict() -> None:
    coordinator, _ = await _created()
    await coordinator.transition(
        plan_id="regional-recovery",
        expected_storage_revision=0,
        expected_state=RecoveryState.DRAFT,
        target=RecoveryState.READY,
        actor_ref="group:operations",
        at=_AT + timedelta(seconds=1),
        evidence_refs=("evidence://ready/one",),
    )
    with pytest.raises(RecoveryWriteConflictError, match="revision"):
        await coordinator.transition(
            plan_id="regional-recovery",
            expected_storage_revision=0,
            expected_state=RecoveryState.DRAFT,
            target=RecoveryState.READY,
            actor_ref="group:operations",
            at=_AT + timedelta(seconds=1),
            evidence_refs=("evidence://ready/two",),
        )


async def test_corrupt_or_wrong_key_record_fails_closed() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "control-plane-recovery:regional-recovery",
        {"schema_version": 99, "revision": 0},
    )
    coordinator = RecoveryPlanCoordinator(state_store=store)
    with pytest.raises(RecoveryRecordError, match="corrupt"):
        await coordinator.get("regional-recovery")


async def test_missing_plan_transition_is_rejected() -> None:
    coordinator = RecoveryPlanCoordinator(state_store=InMemoryStateStore())
    with pytest.raises(RecoveryWriteConflictError, match="does not exist"):
        await coordinator.transition(
            plan_id="missing",
            expected_storage_revision=0,
            expected_state=RecoveryState.DRAFT,
            target=RecoveryState.READY,
            actor_ref="group:operations",
            at=_AT,
            evidence_refs=("evidence://ready",),
        )
