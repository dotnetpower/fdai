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


async def test_repository_and_service_edge_branches(
    service: AssignmentCaseService,
    store: InMemoryStateStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from unittest.mock import AsyncMock

    from fdai.core.human_assignment.command_receipt import AssignmentCommandReceipt
    from fdai.core.human_assignment.errors import (
        AssignmentPermissionError,
        AssignmentServiceError,
    )
    from fdai.core.human_assignment.repository import (
        _state_key,
        assignment_case_id,
        create_case_state,
        list_case_states,
        load_case_state,
        persist_case_state,
    )

    # Repository helpers
    with pytest.raises(AssignmentServiceError, match="idempotency_key MUST be non-empty"):
        assignment_case_id("requester-1", "   ")
    with pytest.raises(AssignmentServiceError, match="case_id MUST be non-empty"):
        _state_key("")
    with pytest.raises(AssignmentServiceError, match="not found"):
        await load_case_state(store, "nonexistent")
    with pytest.raises(AssignmentServiceError, match="limit MUST be between"):
        await list_case_states(store, limit=0)
    with pytest.raises(AssignmentServiceError, match="cursor MUST be between"):
        await list_case_states(store, limit=10, offset=-1)

    # Permission checks
    with pytest.raises(AssignmentPermissionError, match="manage-group-membership"):
        await service.list_case_page(principal=principal("reader-1", Role.READER))
    with pytest.raises(AssignmentPermissionError, match="MUST match requester_ref"):
        await service.create_case(
            principal=principal("other-owner"),
            intent=intent(),
            now=NOW,
        )

    # Naive timestamp rejected
    with pytest.raises(AssignmentServiceError, match="timezone-aware"):
        await service.create_case(
            principal=principal("requester-1"),
            intent=intent(),
            now=datetime(2026, 8, 1),
        )

    cmd1 = AssignmentCommandReceipt("operator-" + "a" * 32, "a" * 64)
    cmd2 = AssignmentCommandReceipt("operator-" + "b" * 32, "b" * 64)
    cmd3 = AssignmentCommandReceipt("operator-" + "c" * 32, "c" * 64)
    created = await service.create_case(
        principal=principal("requester-1"),
        intent=intent(),
        now=NOW,
        command_receipt=cmd1,
    )
    page, total = await service.list_case_page(principal=principal("requester-1"))
    assert total == 1 and page == (created,)

    # Conflicting command receipt on draft replay
    with pytest.raises(AssignmentConflictError, match="different command"):
        await service.create_case(
            principal=principal("requester-1"),
            intent=intent(),
            now=NOW,
            command_receipt=cmd2,
        )

    # Race branches in create_case_state
    orig_write = store.write_state_with_audit_if_absent
    monkeypatch.setattr(store, "write_state_with_audit_if_absent", AsyncMock(return_value=False))
    raced_draft = replace(created, case_id="raced-lost")
    with pytest.raises(RuntimeError, match="lost after an atomic create race"):
        await create_case_state(store, raced_draft, actor_ref="requester-1", at=NOW)
    monkeypatch.setattr(store, "write_state_with_audit_if_absent", orig_write)

    # Submit permission and replay checks
    with pytest.raises(AssignmentPermissionError, match="only the requester"):
        await service.submit_for_review(
            principal=principal("other-owner"),
            case_id=created.case_id,
            expected_revision=created.revision,
            now=NOW,
        )
    pending = await service.submit_for_review(
        principal=principal("requester-1"),
        case_id=created.case_id,
        expected_revision=created.revision,
        now=NOW + timedelta(minutes=1),
        command_receipt=cmd2,
    )
    assert (
        await service.submit_for_review(
            principal=principal("requester-1"),
            case_id=created.case_id,
            expected_revision=created.revision,
            now=NOW + timedelta(minutes=1),
            command_receipt=cmd2,
        )
        == pending
    )
    with pytest.raises(AssignmentConflictError, match="different command"):
        await service.submit_for_review(
            principal=principal("requester-1"),
            case_id=created.case_id,
            expected_revision=created.revision,
            now=NOW + timedelta(minutes=1),
            command_receipt=cmd3,
        )

    # persist_case_state CAS race when already persisted vs stale
    orig_cas = store.compare_and_set_state_with_audit
    monkeypatch.setattr(store, "compare_and_set_state_with_audit", AsyncMock(return_value=False))
    assert (
        await persist_case_state(
            store,
            created,
            pending,
            expected_revision=created.revision,
            audit_kind=AssignmentAuditKind.TRANSITIONED,
            actor_ref="requester-1",
            at=NOW,
        )
        == pending
    )
    with pytest.raises(StaleAssignmentRevisionError):
        await persist_case_state(
            store,
            created,
            replace(pending, degraded_reason="different"),
            expected_revision=created.revision,
            audit_kind=AssignmentAuditKind.TRANSITIONED,
            actor_ref="requester-1",
            at=NOW,
        )
    monkeypatch.setattr(store, "compare_and_set_state_with_audit", orig_cas)

    # Review conflicts
    approved = await approve(service, pending, "owner-1", at=NOW + timedelta(minutes=2))
    with pytest.raises(AssignmentConflictError, match="different decision"):
        await service.review(
            principal=principal("owner-1"),
            case_id=approved.case_id,
            expected_revision=approved.revision,
            decision=ReviewDecision.REJECT,
            now=NOW + timedelta(minutes=3),
        )
    with pytest.raises(AssignmentConflictError, match="not pending review"):
        await approve(service, approved, "owner-2", at=NOW + timedelta(minutes=3))

    # Idempotent _advance and record_effect / mark_degraded replays
    opened = await service.open_ownership_pr(
        case_id=approved.case_id,
        expected_revision=approved.revision,
        actor_ref="Forseti",
        now=NOW + timedelta(minutes=3),
    )
    assert (
        await service.open_ownership_pr(
            case_id=opened.case_id,
            expected_revision=opened.revision,
            actor_ref="Forseti",
            now=NOW + timedelta(minutes=3),
        )
        == opened
    )
    own_receipt = effect(EffectKind.OWNERSHIP, at=NOW + timedelta(minutes=4))
    merged = await service.record_effect(
        case_id=opened.case_id,
        expected_revision=opened.revision,
        receipt=own_receipt,
        actor_ref="Saga",
    )
    assert (
        await service.record_effect(
            case_id=merged.case_id,
            expected_revision=merged.revision,
            receipt=own_receipt,
            actor_ref="Saga",
        )
        == merged
    )
    with pytest.raises(AssignmentConflictError, match="different receipt"):
        await service.record_effect(
            case_id=merged.case_id,
            expected_revision=merged.revision,
            receipt=replace(own_receipt, digest="other-digest"),
            actor_ref="Saga",
        )

    with pytest.raises(AssignmentConflictError, match="revision is stale"):
        await service.begin_iam_apply(
            case_id=merged.case_id,
            expected_revision=999,
            actor_ref="Thor",
            now=NOW + timedelta(minutes=5),
        )
    with pytest.raises(AssignmentConflictError, match="requires verified removal"):
        await service.close_revocation_target(case_id=merged.case_id, actor_ref="Saga")

    degraded = await service.mark_degraded(
        case_id=merged.case_id,
        expected_revision=merged.revision,
        reason_code="iam_timeout",
        actor_ref="Vidar",
        now=NOW + timedelta(minutes=5),
    )
    assert (
        await service.mark_degraded(
            case_id=degraded.case_id,
            expected_revision=degraded.revision,
            reason_code="iam_timeout",
            actor_ref="Vidar",
            now=NOW + timedelta(minutes=6),
        )
        == degraded
    )


async def test_service_prepare_and_record_human_access_inverse_and_revoke() -> None:
    import runpy
    from dataclasses import replace
    from pathlib import Path

    from fdai.core.human_assignment.execution_material import (
        HumanAccessMaterialBuilder,
        HumanAccessMaterialStore,
    )
    from fdai.shared.contracts.models import Action
    from fdai_service_contracts.human_access import HumanAccessOperation, HumanAccessPlan
    from fdai_service_contracts.human_access_execution import (
        HumanAccessExecutionMaterial,
        canonical_human_access_json,
        human_access_record_digest,
    )
    from fdai_service_contracts.human_access_recovery import HumanAccessInverseBinding
    from tests.core.human_assignment.test_access_apply import _ownership_merged
    from tests.core.human_assignment.test_revocation_delivery import _coordinator, _reviewed

    _support = runpy.run_path(
        str(
            Path(__file__).resolve().parents[5]
            / "packages/service-contracts/tests/test_human_access_execution.py"
        )
    )
    at, sample = _support["AT"], _support["material"]

    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    case = await _ownership_merged(cases)
    plan = HumanAccessPlan(
        case.case_id,
        case.intent.subject.subject_id,
        "group:reader",
        HumanAccessOperation.GRANT,
        "key:svc-inv",
    )
    raw = {
        **sample().action().model_dump(mode="json"),
        "params": {"case_id": case.case_id, "expected_revision": case.revision},
        "target_resource_ref": plan.membership_lock_key.removeprefix("fdai:resource:"),
    }
    builder = HumanAccessMaterialBuilder(
        cases, HumanAccessMaterialStore(store), {Role.READER: "group:reader"}
    )
    mat = await builder.build(
        action=Action.model_validate(raw),
        promotion_record={"action_type": raw["action_type"], "mode": "enforce"},
        at=at,
    )
    prepared = await cases.prepare_human_access(material=mat, actor_ref="Muninn", now=at)

    # Conflicting forward preparation rejected
    other_raw = {**raw, "action_id": "00000000-0000-0000-0000-000000000091"}
    other_mat = HumanAccessExecutionMaterial.model_validate(
        {
            **mat.model_dump(mode="json"),
            "action_json": canonical_human_access_json(other_raw),
        }
    )
    with pytest.raises(AssignmentConflictError, match="another reviewed Action"):
        await cases.prepare_human_access(material=other_mat, actor_ref="Muninn", now=at)

    # Degrade and prepare inverse recovery + record inverse recovery effect
    degraded = await cases.mark_degraded(
        case_id=case.case_id,
        expected_revision=prepared.revision,
        reason_code="mismatch",
        actor_ref="Vidar",
        now=at + timedelta(seconds=1),
    )
    inv_raw = {
        **raw,
        "action_id": "00000000-0000-0000-0000-000000000092",
        "action_type": "ops.revoke-human-access",
        "operation": "detach",
        "created_at": at + timedelta(seconds=2),
        "params": {
            "case_id": degraded.case_id,
            "expected_revision": degraded.revision,
            "recovery_of": str(mat.action().action_id),
        },
        "action_type_ref": {
            "kind": "action",
            "name": "ops.revoke-human-access",
            "version": "1.0.0",
            "catalog_digest": "sha256:" + "a" * 64,
        },
    }
    inv_mat = HumanAccessExecutionMaterial(
        action_json=canonical_human_access_json(
            Action.model_validate(inv_raw).model_dump(mode="json")
        ),
        subject_id=mat.subject_id,
        group_id=mat.group_id,
        requested_role=mat.requested_role,
        requester_ref=mat.requester_ref,
        case_record_digest=human_access_record_digest(degraded.to_dict()),
        role_groups_digest=mat.role_groups_digest,
        promotion_record_digest=mat.promotion_record_digest,
        approval_ids=("approval:inv-1",),
        recorded_at=at + timedelta(seconds=2),
        expires_at=at + timedelta(minutes=5, seconds=2),
        inverse=HumanAccessInverseBinding(
            original_action_id=mat.action().action_id,
            original_action_digest=mat.action_digest,
            original_material_digest=mat.digest,
            original_idempotency_key=mat.action().idempotency_key,
            original_target_digest=mat.membership_plan().target_digest,
            original_attempt_digest="a" * 64,
            original_before_membership=False,
            original_receipt_ref="entra:receipt:1",
            original_completed_at=at,
            target_fence_digest="sha256:" + "b" * 64,
            target_fence_generation=1,
            demand_digest="c" * 64,
        ),
    )

    with pytest.raises(AssignmentConflictError, match="inverse preparation source changed"):
        await cases.prepare_human_access(
            material=inv_mat, actor_ref="Muninn", now=inv_mat.expires_at
        )

    inv_prepared = await cases.prepare_human_access(
        material=inv_mat, actor_ref="Muninn", now=at + timedelta(seconds=3)
    )
    assert (
        await cases.prepare_human_access(
            material=inv_mat, actor_ref="Muninn", now=at + timedelta(seconds=4)
        )
        == inv_prepared
    )

    with pytest.raises(AssignmentConflictError, match="inverse effect source changed"):
        await cases.record_human_access_recovery(
            material=mat,
            receipt=effect(EffectKind.IAM, at=at + timedelta(seconds=5)),
            actor_ref="Saga",
        )

    rec_receipt = effect(EffectKind.IAM, at=at + timedelta(seconds=5))
    recovered = await cases.record_human_access_recovery(
        material=inv_mat, receipt=rec_receipt, actor_ref="Saga"
    )
    assert recovered.iam_recovery_effect == rec_receipt
    assert (
        await cases.record_human_access_recovery(
            material=inv_mat, receipt=rec_receipt, actor_ref="Saga"
        )
        == recovered
    )
    with pytest.raises(AssignmentConflictError, match="already has a different effect"):
        await cases.record_human_access_recovery(
            material=inv_mat,
            receipt=replace(rec_receipt, digest="different-digest"),
            actor_ref="Saga",
        )

    # Revocation preparation holds target case
    coord = await _coordinator()
    approved_rev = await _reviewed(coord.cases)
    rev_plan = HumanAccessPlan(
        approved_rev.case_id,
        approved_rev.intent.subject.subject_id,
        "group:reader",
        HumanAccessOperation.REVOKE,
        "key:svc-rev",
    )
    rev_raw = {
        **inv_raw,
        "action_id": "00000000-0000-0000-0000-000000000093",
        "created_at": at,
        "target_resource_ref": rev_plan.membership_lock_key.removeprefix("fdai:resource:"),
        "params": {
            "case_id": approved_rev.case_id,
            "expected_revision": approved_rev.revision,
            "replacement_revisions": {"primary": 7, "backup": 7},
        },
    }
    rev_builder = HumanAccessMaterialBuilder(
        coord.cases, HumanAccessMaterialStore(coord.cases.store), {Role.READER: "group:reader"}
    )
    rev_mat = await rev_builder.build(
        action=Action.model_validate(rev_raw),
        promotion_record={"action_type": "ops.revoke-human-access", "mode": "enforce"},
        at=at,
    )
    rev_prep = await coord.cases.prepare_human_access(
        material=rev_mat, actor_ref="Muninn", now=at + timedelta(seconds=1)
    )
    assert rev_prep.state is AssignmentState.IAM_APPLYING
    assert (await coord.cases.get_case("old")).revocation_case_id == approved_rev.case_id
