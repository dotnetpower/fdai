"""Bounded executor access-grant lifecycle tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.execution_authorization import (
    AccessGrantDecision,
    AccessGrantRequestConflictError,
    AccessGrantRequestPermissionError,
    AccessGrantRequestService,
    AccessGrantRequestStatus,
)
from fdai.shared.providers.testing import InMemoryStateStore

NOW = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)


async def _submitted() -> tuple[AccessGrantRequestService, object]:
    service = AccessGrantRequestService(store=InMemoryStateStore())
    request = await service.submit(
        idempotency_key="grant-1",
        original_action_id="action-1",
        authorization_decision_digest="decision-v1",
        requirement_id="requirement.object-write",
        capability_id="object.write",
        execution_profile="change-executor",
        executor_identity_ref="identity/change",
        scope_ref="scope://example/account/prod/store-1",
        grant_mode="time_bound",
        mapping_digest="mapping-v1",
        plan_digest="plan-v1",
        requester_ref="requester-1",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        quorum=1,
        approver_roles=frozenset({"owner"}),
    )
    return service, request


async def test_exact_grant_lifecycle_reaches_verified_then_revoked() -> None:
    service, request = await _submitted()
    approved = await service.decide(
        request_id=request.request_id,
        reviewer_ref="owner-1",
        reviewer_roles=frozenset({"owner"}),
        decision=AccessGrantDecision.APPROVE,
        reason="Bounded operation reviewed.",
        decided_at=NOW + timedelta(minutes=1),
    )
    assert approved.status is AccessGrantRequestStatus.APPROVED
    applied = await service.record_apply(
        request_id=request.request_id,
        deployer_ref="identity/deployer",
        plan_digest="plan-v1",
        receipt_ref="receipt-1",
        applied_at=NOW + timedelta(minutes=2),
    )
    assert applied.status is AccessGrantRequestStatus.APPLIED
    verified = await service.verify(
        request_id=request.request_id,
        observation_digest="observation-v1",
        verifier_ref="identity/probe",
        verified_at=NOW + timedelta(minutes=3),
    )
    assert verified.status is AccessGrantRequestStatus.VERIFIED
    revoked = await service.revoke(
        request_id=request.request_id,
        revoked_by="identity/deployer",
        revoked_at=NOW + timedelta(minutes=4),
    )
    assert revoked.status is AccessGrantRequestStatus.REVOKED
    assert await service.store.verify_chain()  # type: ignore[attr-defined]


async def test_requester_cannot_approve_own_grant() -> None:
    service, request = await _submitted()
    with pytest.raises(AccessGrantRequestPermissionError, match="self-approved"):
        await service.decide(
            request_id=request.request_id,
            reviewer_ref="REQUESTER-1",
            reviewer_roles=frozenset({"owner"}),
            decision=AccessGrantDecision.APPROVE,
            reason="Attempted self approval.",
            decided_at=NOW + timedelta(minutes=1),
        )


async def test_apply_requires_approved_exact_plan() -> None:
    service, request = await _submitted()
    await service.decide(
        request_id=request.request_id,
        reviewer_ref="owner-1",
        reviewer_roles=frozenset({"owner"}),
        decision=AccessGrantDecision.APPROVE,
        reason="Bounded operation reviewed.",
        decided_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(AccessGrantRequestConflictError, match="plan digest"):
        await service.record_apply(
            request_id=request.request_id,
            deployer_ref="identity/deployer",
            plan_digest="plan-v2",
            receipt_ref="receipt-1",
            applied_at=NOW + timedelta(minutes=2),
        )


async def test_executor_cannot_apply_its_own_grant() -> None:
    service, request = await _submitted()
    await service.decide(
        request_id=request.request_id,
        reviewer_ref="owner-1",
        reviewer_roles=frozenset({"owner"}),
        decision=AccessGrantDecision.APPROVE,
        reason="Bounded operation reviewed.",
        decided_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(AccessGrantRequestPermissionError, match="own grant"):
        await service.record_apply(
            request_id=request.request_id,
            deployer_ref="IDENTITY/CHANGE",
            plan_digest="plan-v1",
            receipt_ref="receipt-1",
            applied_at=NOW + timedelta(minutes=2),
        )


async def test_expiry_is_a_terminal_audited_transition() -> None:
    service, request = await _submitted()
    expired = await service.expire(
        request_id=request.request_id,
        now=NOW + timedelta(minutes=31),
    )
    assert expired.status is AccessGrantRequestStatus.EXPIRED


async def test_idempotency_key_replay_requires_same_intent() -> None:
    service, request = await _submitted()
    replay = await service.submit(
        idempotency_key="grant-1",
        original_action_id="action-1",
        authorization_decision_digest="decision-v1",
        requirement_id="requirement.object-write",
        capability_id="object.write",
        execution_profile="change-executor",
        executor_identity_ref="identity/change",
        scope_ref="scope://example/account/prod/store-1",
        grant_mode="time_bound",
        mapping_digest="mapping-v1",
        plan_digest="plan-v1",
        requester_ref="requester-1",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        quorum=1,
        approver_roles=frozenset({"owner"}),
    )
    assert replay.request_id == request.request_id


async def test_same_action_decision_creates_distinct_requests_per_scope() -> None:
    service, request = await _submitted()
    second = await service.submit(
        idempotency_key="grant-1",
        original_action_id="action-1",
        authorization_decision_digest="decision-v1",
        requirement_id="requirement.object-write.account",
        capability_id="object.write",
        execution_profile="change-executor",
        executor_identity_ref="identity/change",
        scope_ref="scope://example/account",
        grant_mode="time_bound",
        mapping_digest="mapping-v1",
        plan_digest="plan-v2",
        requester_ref="requester-1",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        quorum=1,
        approver_roles=frozenset({"owner"}),
    )

    assert second.request_id != request.request_id


async def test_quorum_requires_distinct_approvers() -> None:
    service = AccessGrantRequestService(store=InMemoryStateStore())
    request = await service.submit(
        idempotency_key="grant-quorum",
        original_action_id="action-quorum",
        authorization_decision_digest="decision-quorum",
        requirement_id="requirement.object-write",
        capability_id="object.write",
        execution_profile="change-executor",
        executor_identity_ref="identity/change",
        scope_ref="scope://example/account/prod/store-1",
        grant_mode="time_bound",
        mapping_digest="mapping-v1",
        plan_digest="plan-v1",
        requester_ref="requester-1",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        quorum=2,
        approver_roles=frozenset({"owner"}),
    )
    first = await service.decide(
        request_id=request.request_id,
        reviewer_ref="owner-1",
        reviewer_roles=frozenset({"owner"}),
        decision=AccessGrantDecision.APPROVE,
        reason="First independent review.",
        decided_at=NOW + timedelta(minutes=1),
    )
    assert first.status is AccessGrantRequestStatus.PENDING
    with pytest.raises(AccessGrantRequestConflictError, match="already approved"):
        await service.decide(
            request_id=request.request_id,
            reviewer_ref="OWNER-1",
            reviewer_roles=frozenset({"owner"}),
            decision=AccessGrantDecision.APPROVE,
            reason="Duplicate review.",
            decided_at=NOW + timedelta(minutes=2),
        )
    second = await service.decide(
        request_id=request.request_id,
        reviewer_ref="owner-2",
        reviewer_roles=frozenset({"owner"}),
        decision=AccessGrantDecision.APPROVE,
        reason="Second independent review.",
        decided_at=NOW + timedelta(minutes=2),
    )
    assert second.status is AccessGrantRequestStatus.APPROVED
    assert second.approved_by == ("owner-1", "owner-2")


async def test_expired_request_cannot_be_approved() -> None:
    service, request = await _submitted()
    with pytest.raises(AccessGrantRequestConflictError, match="expired"):
        await service.decide(
            request_id=request.request_id,
            reviewer_ref="owner-1",
            reviewer_roles=frozenset({"owner"}),
            decision=AccessGrantDecision.APPROVE,
            reason="Late review.",
            decided_at=NOW + timedelta(minutes=31),
        )


async def test_audit_actor_tracks_reviewer_and_deployer() -> None:
    service, request = await _submitted()
    await service.decide(
        request_id=request.request_id,
        reviewer_ref="owner-1",
        reviewer_roles=frozenset({"owner"}),
        decision=AccessGrantDecision.APPROVE,
        reason="Bounded operation reviewed.",
        decided_at=NOW + timedelta(minutes=1),
    )
    await service.record_apply(
        request_id=request.request_id,
        deployer_ref="identity/deployer",
        plan_digest="plan-v1",
        receipt_ref="receipt-1",
        applied_at=NOW + timedelta(minutes=2),
    )
    actors = [record["entry"]["actor"] for record in service.store.audit_entries]  # type: ignore[attr-defined]
    assert actors == ["requester-1", "owner-1", "identity/deployer"]


async def test_concurrent_distinct_approvals_complete_quorum() -> None:
    service = AccessGrantRequestService(store=InMemoryStateStore())
    request = await service.submit(
        idempotency_key="grant-concurrent",
        original_action_id="action-concurrent",
        authorization_decision_digest="decision-concurrent",
        requirement_id="requirement.object-write",
        capability_id="object.write",
        execution_profile="change-executor",
        executor_identity_ref="identity/change",
        scope_ref="scope://example/account/prod/store-1",
        grant_mode="time_bound",
        mapping_digest="mapping-v1",
        plan_digest="plan-v1",
        requester_ref="requester-1",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        quorum=2,
        approver_roles=frozenset({"owner"}),
    )
    results = await asyncio.gather(
        service.decide(
            request_id=request.request_id,
            reviewer_ref="owner-1",
            reviewer_roles=frozenset({"owner"}),
            decision=AccessGrantDecision.APPROVE,
            reason="First concurrent review.",
            decided_at=NOW + timedelta(minutes=1),
        ),
        service.decide(
            request_id=request.request_id,
            reviewer_ref="owner-2",
            reviewer_roles=frozenset({"owner"}),
            decision=AccessGrantDecision.APPROVE,
            reason="Second concurrent review.",
            decided_at=NOW + timedelta(minutes=1),
        ),
    )
    assert {result.status for result in results} == {
        AccessGrantRequestStatus.PENDING,
        AccessGrantRequestStatus.APPROVED,
    }
    assert results[-1].approved_by == ("owner-1", "owner-2")


async def test_pending_requests_are_filtered_by_reviewer_role_and_expiry() -> None:
    service, owner_request = await _submitted()
    approver_request = await service.submit(
        idempotency_key="grant-approver",
        original_action_id="action-approver",
        authorization_decision_digest="decision-approver",
        requirement_id="requirement.metrics-read",
        capability_id="kubernetes.metrics.read",
        execution_profile="observation-reader",
        executor_identity_ref="identity/reader",
        scope_ref="scope://example/cluster/namespace/example-app",
        grant_mode="time_bound",
        mapping_digest="mapping-metrics-v1",
        plan_digest="plan-metrics-v1",
        requester_ref="heimdall",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        quorum=1,
        approver_roles=frozenset({"approver"}),
    )

    visible = await service.list_pending_for_roles(
        reviewer_ref="reviewer-1",
        reviewer_roles=frozenset({"Approver"}),
        now=NOW + timedelta(minutes=1),
        limit=10,
    )

    assert visible == (approver_request,)
    assert owner_request not in visible
    assert (
        await service.list_pending_for_roles(
            reviewer_ref="reviewer-1",
            reviewer_roles=frozenset({"Approver"}),
            now=NOW + timedelta(minutes=11),
            limit=10,
        )
        == ()
    )
    assert (
        await service.list_pending_for_roles(
            reviewer_ref="heimdall",
            reviewer_roles=frozenset({"Approver"}),
            now=NOW + timedelta(minutes=1),
            limit=10,
        )
        == ()
    )
