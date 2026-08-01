from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.human_assignment import (
    AssignmentAuditKind,
    AssignmentCase,
    AssignmentCaseService,
    AssignmentConflictError,
    AssignmentCoverageError,
    AssignmentIntent,
    AssignmentState,
    DutyBinding,
    EffectKind,
    EffectReceipt,
    ProviderSubject,
    ReviewDecision,
    StaleAssignmentRevisionError,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship.model import Duty
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 8, 1, tzinfo=UTC)


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


@pytest.fixture
def service(store: InMemoryStateStore) -> AssignmentCaseService:
    return AssignmentCaseService(store)


def principal(oid: str, role: Role = Role.OWNER) -> Principal:
    return Principal(oid=oid, roles=frozenset({role}))


def intent(
    *,
    role: Role = Role.READER,
    idempotency_key: str = "assignment-1",
    subject_id: str = "target-1",
) -> AssignmentIntent:
    return AssignmentIntent(
        idempotency_key=idempotency_key,
        subject=ProviderSubject("entra", subject_id),
        requested_role=role,
        duty_bindings=(DutyBinding("Odin", Duty.PRIMARY, "scope:platform"),),
        goal_refs=("goal:odin:operations:v1",),
        requester_ref="requester-1",
        justification="Assign platform ownership and bounded console access.",
    )


async def create_pending(
    service: AssignmentCaseService,
    *,
    role: Role = Role.READER,
) -> AssignmentCase:
    created = await service.create_case(
        principal=principal("requester-1"),
        intent=intent(role=role),
        now=NOW,
    )
    return await service.submit_for_review(
        principal=principal("requester-1"),
        case_id=created.case_id,
        expected_revision=created.revision,
        now=NOW + timedelta(minutes=1),
    )


async def approve(
    service: AssignmentCaseService,
    case: AssignmentCase,
    reviewer: str,
    *,
    at: datetime,
) -> AssignmentCase:
    return await service.review(
        principal=principal(reviewer),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=ReviewDecision.APPROVE,
        now=at,
    )


def effect(kind: EffectKind, *, at: datetime) -> EffectReceipt:
    return EffectReceipt(
        kind=kind,
        receipt_ref=f"receipt:{kind.value}:1",
        digest=f"digest-{kind.value}",
        received_at=at,
    )


async def test_create_replays_same_intent_and_rejects_key_conflict(
    service: AssignmentCaseService,
    store: InMemoryStateStore,
) -> None:
    first = await service.create_case(
        principal=principal("requester-1"),
        intent=intent(),
        now=NOW,
    )
    replay = await service.create_case(
        principal=principal("REQUESTER-1"),
        intent=intent(),
        now=NOW + timedelta(hours=1),
    )

    assert replay == first
    assert len(tuple(store.audit_entries)) == 1
    with pytest.raises(AssignmentConflictError, match="different intent"):
        await service.create_case(
            principal=principal("requester-1"),
            intent=intent(subject_id="other-target"),
            now=NOW,
        )


async def test_stale_revision_is_rejected(service: AssignmentCaseService) -> None:
    created = await service.create_case(
        principal=principal("requester-1"),
        intent=intent(),
        now=NOW,
    )

    with pytest.raises(StaleAssignmentRevisionError, match="stale"):
        await service.submit_for_review(
            principal=principal("requester-1"),
            case_id=created.case_id,
            expected_revision=0,
            now=NOW,
        )


@pytest.mark.parametrize("reviewer", ["REQUESTER-1", " TARGET-1 "])
async def test_requester_and_target_cannot_review_after_normalization(
    service: AssignmentCaseService,
    reviewer: str,
) -> None:
    pending = await create_pending(service)

    with pytest.raises(AssignmentCoverageError, match="requester and target"):
        await approve(service, pending, reviewer, at=NOW + timedelta(minutes=2))


async def test_elevated_role_requires_two_distinct_owner_reviews(
    service: AssignmentCaseService,
) -> None:
    pending = await create_pending(service, role=Role.OWNER)
    first = await approve(service, pending, "owner-1", at=NOW + timedelta(minutes=2))

    assert first.state is AssignmentState.PENDING_REVIEW
    assert first.revision == pending.revision + 1
    replay = await approve(service, first, "OWNER-1", at=NOW + timedelta(minutes=3))
    assert replay == first
    second = await approve(service, first, "owner-2", at=NOW + timedelta(minutes=3))
    assert second.state is AssignmentState.APPROVED
    assert len(second.reviews) == 2


async def test_partial_effect_failure_recovers_without_losing_ownership_receipt(
    service: AssignmentCaseService,
    store: InMemoryStateStore,
) -> None:
    pending = await create_pending(service)
    approved = await approve(service, pending, "owner-1", at=NOW + timedelta(minutes=2))
    opened = await service.open_ownership_pr(
        case_id=approved.case_id,
        expected_revision=approved.revision,
        actor_ref="Forseti",
        now=NOW + timedelta(minutes=3),
    )
    merged = await service.record_effect(
        case_id=opened.case_id,
        expected_revision=opened.revision,
        receipt=effect(EffectKind.OWNERSHIP, at=NOW + timedelta(minutes=4)),
        actor_ref="Saga",
    )
    applying = await service.begin_iam_apply(
        case_id=merged.case_id,
        expected_revision=merged.revision,
        actor_ref="Thor",
        now=NOW + timedelta(minutes=5),
    )
    degraded = await service.mark_degraded(
        case_id=applying.case_id,
        expected_revision=applying.revision,
        reason_code="iam_provider_unavailable",
        actor_ref="Vidar",
        now=NOW + timedelta(minutes=6),
    )
    retrying = await service.begin_iam_apply(
        case_id=degraded.case_id,
        expected_revision=degraded.revision,
        actor_ref="Thor",
        now=NOW + timedelta(minutes=7),
    )
    active = await service.record_effect(
        case_id=retrying.case_id,
        expected_revision=retrying.revision,
        receipt=effect(EffectKind.IAM, at=NOW + timedelta(minutes=8)),
        actor_ref="Saga",
    )

    assert active.state is AssignmentState.ACTIVE
    assert active.effect_kinds == frozenset({EffectKind.OWNERSHIP, EffectKind.IAM})
    assert active.degraded_reason is None
    audit_kinds = {record["entry"]["action_kind"] for record in store.audit_entries}
    assert AssignmentAuditKind.EFFECT_RECEIVED.value in audit_kinds
    assert AssignmentAuditKind.DEGRADED.value in audit_kinds
    assert AssignmentAuditKind.ACTIVATED.value in audit_kinds


async def test_iam_receipt_cannot_activate_before_ownership_merge(
    service: AssignmentCaseService,
) -> None:
    pending = await create_pending(service)
    approved = await approve(service, pending, "owner-1", at=NOW + timedelta(minutes=2))

    with pytest.raises(AssignmentConflictError, match="not valid"):
        await service.record_effect(
            case_id=approved.case_id,
            expected_revision=approved.revision,
            receipt=effect(EffectKind.IAM, at=NOW + timedelta(minutes=3)),
            actor_ref="Saga",
        )


async def test_supersession_is_idempotent_and_audited(
    service: AssignmentCaseService,
    store: InMemoryStateStore,
) -> None:
    created = await service.create_case(
        principal=principal("requester-1"),
        intent=intent(),
        now=NOW,
    )
    superseded = await service.supersede(
        case_id=created.case_id,
        expected_revision=created.revision,
        successor_case_id="case-successor",
        actor_ref="Forseti",
        now=NOW + timedelta(minutes=1),
    )
    replay = await service.supersede(
        case_id=created.case_id,
        expected_revision=created.revision,
        successor_case_id="case-successor",
        actor_ref="Forseti",
        now=NOW + timedelta(minutes=2),
    )

    assert replay == superseded
    assert superseded.state is AssignmentState.SUPERSEDED
    kinds = [record["entry"]["action_kind"] for record in store.audit_entries]
    assert kinds.count(AssignmentAuditKind.SUPERSEDED.value) == 1


async def test_audit_entries_are_content_free_and_cover_required_kinds(
    service: AssignmentCaseService,
    store: InMemoryStateStore,
) -> None:
    pending = await create_pending(service)
    await approve(service, pending, "owner-1", at=NOW + timedelta(minutes=2))

    entries = [record["entry"] for record in store.audit_entries]
    kinds = {entry["action_kind"] for entry in entries}
    assert AssignmentAuditKind.REQUESTED.value in kinds
    assert AssignmentAuditKind.REVIEWED.value in kinds
    serialized = repr(entries)
    assert "target-1" not in serialized
    assert "Assign platform ownership" not in serialized
    assert "requester-1" not in serialized
    assert all(str(entry["actor"]).startswith("sha256:") for entry in entries)
    assert await store.verify_chain()
