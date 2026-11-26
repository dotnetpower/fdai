"""Existing HIL slot readback and no legacy direct-execution fallback."""

from __future__ import annotations

import runpy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.human_assignment.execution_approval import HumanAccessApprovalService
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.hil_resume.test_coordinator import _coordinator

_support = runpy.run_path(
    str(
        Path(__file__).resolve().parents[5]
        / "packages/service-contracts/tests/test_human_access_execution.py"
    )
)
AT, material = _support["AT"], _support["material"]


@pytest.fixture
def fixture():
    store = InMemoryStateStore()
    time = {"at": AT + timedelta(seconds=1)}
    owners = SimpleNamespace(is_current_owner=AsyncMock(return_value=True))
    source = AsyncMock()
    service = HumanAccessApprovalService(
        store, owners, source, lambda: time["at"], lambda _person, _action: True
    )
    return service, time, owners, source


async def decide(service, value, *, approvers=None):
    for index, approval_id in enumerate(value.approval_ids):
        await service.store.write_state(
            "operator-hil-decision:" + approval_id,
            {
                "approval_id": approval_id,
                "idempotency_key": f"human-access:{approval_id}",
                "decision": "approve",
                "approver_oid": approvers[index] if approvers else f"person:owner-{index}",
                "decided_at": (AT + timedelta(seconds=1)).isoformat(),
                "receipt_ref": f"operator:decision:{index}",
            },
        )


async def test_parking_uses_existing_hil_records_and_never_writes_human_decisions(fixture):
    service, time, _, _ = fixture
    value = material(elevated=True)
    assert await service.park(value) == value.approval_ids
    rows, total = await service.store.read_state_page("hil_park:", limit=5)
    assert total == 2
    assert all(row["metadata"]["decision_route"] == "human_access" for row in rows)
    assert (await service.store.read_state_page("operator-hil-decision:", limit=5))[1] == 0
    time["at"] += timedelta(seconds=10)
    assert await service.park(value) == value.approval_ids
    assert [row["approval_context"]["expires_at"] for row in rows] == [
        value.expires_at.isoformat()
    ] * 2


async def test_only_current_exact_independent_human_quorum_can_be_read(fixture):
    service, _, _, _ = fixture
    value = material(elevated=True)
    await service.park(value)
    with pytest.raises(ValueError, match="not complete"):
        await service.read_approvals(value)
    await decide(service, value)
    observed = await service.read_approvals(value)
    assert len(observed) == 2 and all(row.material_digest == value.digest for row in observed)


@pytest.mark.parametrize(
    "approvers",
    [
        ["person:subject", "person:second"],
        ["person:requester", "person:second"],
        ["person:same", "person:same"],
    ],
)
async def test_target_self_and_duplicate_quorum_are_rejected(fixture, approvers):
    service, _, _, _ = fixture
    value = material(elevated=True)
    await service.park(value)
    await decide(service, value, approvers=approvers)
    with pytest.raises(ValueError, match="independent"):
        await service.read_approvals(value)


async def test_prior_owner_loss_and_expiry_during_io_cannot_be_hidden(fixture):
    service, time, owners, _ = fixture
    value = material()
    await service.park(value)
    await decide(service, value)
    owners.is_current_owner.side_effect = lambda actor, *, at: actor == value.requester_ref
    with pytest.raises(PermissionError, match="current Owner"):
        await service.read_approvals(value)

    def expire(actor, *, at):
        time["at"] = value.expires_at
        return True

    owners.is_current_owner.side_effect = expire
    with pytest.raises(PermissionError, match="source window"):
        await service.read_approvals(value)


async def test_legacy_hil_coordinator_never_executes_a_human_access_slot(fixture):
    service, _, _, _ = fixture
    value = material(elevated=True)
    await service.park(value)
    coordinator, publisher, _, _ = _coordinator(state_store=service.store)
    result = await coordinator.resolve(
        approval_id=value.approval_ids[0],
        decision=HilDecision.APPROVE,
        approver_oid="person:owner",
    )
    assert result.outcome.value == "owned_route_held"
    assert (await service.store.read_state("hil_park:" + value.approval_ids[0]))[
        "status"
    ] == "pending"
    assert not publisher.records


@pytest.mark.parametrize("policy", [None, lambda _person, _action: False])
async def test_current_owner_without_action_approval_policy_is_held(fixture, policy):
    service, _, _, _ = fixture
    value = material()
    await service.park(value)
    await decide(service, value)
    with pytest.raises(PermissionError, match="ActionType approval policy"):
        await replace(service, can_approve=policy).read_approvals(value)


async def test_approval_service_rejects_expired_window_rebinding_tampered_context_and_bad_time(
    fixture,
):
    service, time, _, _ = fixture
    value = material()

    # Expired window in _current()
    time["at"] = value.expires_at
    with pytest.raises(ValueError, match="original review window expired"):
        await service.park(value)
    time["at"] = AT + timedelta(seconds=1)

    await service.park(value)
    await decide(service, value)

    # Park conflict when HIL slot binds different material
    other = material(elevated=True)
    await service.store.write_state(
        "hil_park:" + value.approval_ids[0],
        {
            **(await service.store.read_state("hil_park:" + value.approval_ids[0])),
            "request_fingerprint": other.digest,
        },
    )
    with pytest.raises(ValueError, match="binds different material"):
        await service.park(value)

    # read_approvals detects tampered approval context
    with pytest.raises(ValueError, match="approval context changed"):
        await service.read_approvals(value)

    # Fresh store to test decision outside review window
    fresh_store = InMemoryStateStore()
    fresh_service = replace(service, store=fresh_store)
    await fresh_service.park(value)
    await fresh_store.write_state(
        "operator-hil-decision:" + value.approval_ids[0],
        {
            "approval_id": value.approval_ids[0],
            "idempotency_key": f"human-access:{value.approval_ids[0]}",
            "decision": "approve",
            "approver_oid": "person:owner-0",
            "decided_at": (AT - timedelta(seconds=5)).isoformat(),
            "receipt_ref": "operator:decision:0",
        },
    )
    with pytest.raises(ValueError, match="outside the original review window"):
        await fresh_service.read_approvals(value)


async def test_case_source_and_current_publisher_branches(monkeypatch):
    from datetime import UTC, datetime

    from fdai.core.human_assignment import AssignmentCaseService
    from fdai.core.human_assignment.execution_material import (
        HumanAccessMaterialBuilder,
        HumanAccessMaterialStore,
    )
    from fdai.core.human_assignment.execution_sources import (
        CURRENT_PREFIX,
        HumanAccessCaseSource,
        HumanAccessCurrentPublisher,
    )
    from fdai.core.rbac.roles import Role
    from fdai.shared.contracts.models import Action, Mode
    from fdai_service_contracts.human_access import HumanAccessOperation, HumanAccessPlan
    from tests.core.human_assignment.test_access_apply import _ownership_merged
    from tests.core.human_assignment.test_revocation_delivery import _coordinator, _reviewed

    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    case = await _ownership_merged(cases)
    groups = {Role.READER: "group:reader"}
    builder = HumanAccessMaterialBuilder(cases, HumanAccessMaterialStore(store), groups)

    plan = HumanAccessPlan(
        case.case_id,
        case.intent.subject.subject_id,
        "group:reader",
        HumanAccessOperation.GRANT,
        "key:source-test",
    )
    raw_action = {
        **material().action().model_dump(mode="json"),
        "params": {"case_id": case.case_id, "expected_revision": case.revision},
        "target_resource_ref": plan.membership_lock_key.removeprefix("fdai:resource:"),
    }
    action = Action.model_validate(raw_action)
    promo_rec = {"action_type": action.action_type, "mode": "enforce", "revision": 1}
    await store.write_state("action_promotion:" + action.action_type, promo_rec)
    mat = await builder.build(action=action, promotion_record=promo_rec, at=AT)

    clock = {"at": AT + timedelta(seconds=1)}
    mode_state = {"mode": Mode.ENFORCE}
    promotions = SimpleNamespace(
        refresh=AsyncMock(),
        mode_of=lambda _at: mode_state["mode"],
    )
    source = HumanAccessCaseSource(cases, groups, promotions, lambda: clock["at"])

    # Unprepared check passes
    await source.check(mat)

    # Expired window
    clock["at"] = mat.expires_at
    with pytest.raises(ValueError, match="source window expired"):
        await source.check(mat)
    clock["at"] = AT + timedelta(seconds=1)

    # Unprepared case evidence changed
    raw_stored = await store.read_state(f"human_assignment:case:{case.case_id}")
    await store.write_state(
        f"human_assignment:case:{case.case_id}",
        {**raw_stored, "revision": case.revision + 9},
    )
    with pytest.raises(ValueError, match="original case evidence changed"):
        await source.check(mat)
    await store.write_state(f"human_assignment:case:{case.case_id}", raw_stored)

    # Role group source changed
    bad_group_source = replace(source, role_group_ids={Role.READER: "group:other"})
    with pytest.raises(ValueError, match="role-group source changed"):
        await bad_group_source.check(mat)

    # Membership target changed (planner returns different group)
    from fdai.core.human_assignment.access_planning import HumanAccessPlanner

    orig_plan = HumanAccessPlanner.plan
    monkeypatch.setattr(
        HumanAccessPlanner,
        "plan",
        AsyncMock(
            return_value=HumanAccessPlan(
                case.case_id,
                case.intent.subject.subject_id,
                "group:mutated",
                HumanAccessOperation.GRANT,
                "key:mutated",
            )
        ),
    )
    with pytest.raises(ValueError, match="membership target changed"):
        await source.check(mat)
    monkeypatch.setattr(HumanAccessPlanner, "plan", orig_plan)

    # Promotion changed or unavailable
    mode_state["mode"] = Mode.SHADOW
    with pytest.raises(ValueError, match="verified promotion changed"):
        await source.check(mat)
    mode_state["mode"] = Mode.ENFORCE

    # Source changed during readback (clock expires during check)
    async def expire_on_refresh(_at: str) -> None:
        clock["at"] = mat.expires_at

    promotions.refresh.side_effect = expire_on_refresh
    with pytest.raises(ValueError, match="changed during readback"):
        await source.check(mat)
    promotions.refresh.side_effect = None
    clock["at"] = AT + timedelta(seconds=1)

    # Publisher requires prepared case
    owners = SimpleNamespace(is_current_owner=AsyncMock(return_value=True))
    approvals = HumanAccessApprovalService(
        store, owners, source.check, lambda: clock["at"], lambda _p, _a: True
    )
    await approvals.park(mat)
    await decide(approvals, mat)
    publisher = HumanAccessCurrentPublisher(source, approvals, lambda: clock["at"])
    with pytest.raises(ValueError, match="requires exact Core preparation"):
        await publisher.observe(mat)

    # Prepare case and test prepared case check + publisher observe (create + update + CAS failure)
    prepared = await cases.prepare_human_access(
        material=mat, actor_ref="Muninn", now=AT + timedelta(seconds=1)
    )
    obs1 = await publisher.observe(mat)
    assert obs1.current_case_revision == prepared.revision
    obs2 = await publisher.observe(mat)
    assert obs2.current_case_revision == prepared.revision
    assert (await store.read_state(CURRENT_PREFIX + mat.digest))["revision"] == 2

    # Publisher refusal when clock jumps after source.check
    calls = 0

    def jumping_clock() -> datetime:
        nonlocal calls
        calls += 1
        return mat.expires_at if calls >= 2 else AT + timedelta(seconds=2)

    bad_pub = replace(publisher, clock=jumping_clock)
    with pytest.raises(ValueError, match="expired"):
        await bad_pub.observe(mat)

    # Publisher concurrent modification
    orig_cas = store.compare_and_set_state_with_audit
    monkeypatch.setattr(store, "compare_and_set_state_with_audit", AsyncMock(return_value=False))
    with pytest.raises(ValueError, match="changed concurrently"):
        await publisher.observe(mat)
    monkeypatch.setattr(store, "compare_and_set_state_with_audit", orig_cas)

    # Prepared case evidence mismatch and outside-transition tamper
    prep_stored = await store.read_state(f"human_assignment:case:{case.case_id}")
    await store.write_state(
        f"human_assignment:case:{case.case_id}",
        {
            **prep_stored,
            "iam_preparation": {
                **prep_stored["iam_preparation"],
                "material_digest": "f" * 64,
            },
        },
    )
    with pytest.raises(ValueError, match="prepared case evidence changed"):
        await source.check(mat)

    await store.write_state(
        f"human_assignment:case:{case.case_id}",
        {**prep_stored, "degraded_reason": "tampered"},
    )
    with pytest.raises(ValueError, match="changed outside the exact transition"):
        await source.check(mat)
    await store.write_state(f"human_assignment:case:{case.case_id}", prep_stored)

    # Inverse material check on HumanAccessCaseSource (missing check_inverse vs provided)
    from fdai_service_contracts.human_access_recovery import HumanAccessInverseBinding

    inv_action_raw = {
        **raw_action,
        "action_id": "00000000-0000-0000-0000-000000000066",
        "action_type": "ops.revoke-human-access",
        "operation": "detach",
        "created_at": AT + timedelta(seconds=2),
        "params": {
            "case_id": case.case_id,
            "expected_revision": prepared.revision,
            "recovery_of": str(action.action_id),
        },
        "action_type_ref": {
            "kind": "action",
            "name": "ops.revoke-human-access",
            "version": "1.0.0",
            "catalog_digest": "sha256:" + "a" * 64,
        },
    }
    degraded = await cases.mark_degraded(
        case_id=case.case_id,
        expected_revision=prepared.revision,
        reason_code="mismatch",
        actor_ref="Vidar",
        now=AT + timedelta(seconds=2),
    )
    inv_action_raw["params"]["expected_revision"] = degraded.revision
    from fdai_service_contracts.human_access_execution import (
        HumanAccessExecutionMaterial,
        canonical_human_access_json,
        human_access_record_digest,
    )

    await store.write_state(
        "action_promotion:ops.revoke-human-access",
        {"action_type": "ops.revoke-human-access", "mode": "enforce", "revision": 1},
    )
    inv_mat = HumanAccessExecutionMaterial(
        action_json=canonical_human_access_json(
            Action.model_validate(inv_action_raw).model_dump(mode="json")
        ),
        subject_id=mat.subject_id,
        group_id=mat.group_id,
        requested_role=mat.requested_role,
        requester_ref=mat.requester_ref,
        case_record_digest=human_access_record_digest(degraded.to_dict()),
        role_groups_digest=mat.role_groups_digest,
        promotion_record_digest=human_access_record_digest(
            {"action_type": "ops.revoke-human-access", "mode": "enforce", "revision": 1}
        ),
        approval_ids=("approval:inv-1",),
        recorded_at=AT + timedelta(seconds=2),
        expires_at=AT + timedelta(minutes=5, seconds=2),
        inverse=HumanAccessInverseBinding(
            original_action_id=action.action_id,
            original_action_digest=mat.action_digest,
            original_material_digest=mat.digest,
            original_idempotency_key=action.idempotency_key,
            original_target_digest=mat.membership_plan().target_digest,
            original_attempt_digest="a" * 64,
            original_before_membership=False,
            original_receipt_ref="entra:receipt:1",
            original_completed_at=AT,
            target_fence_digest="sha256:" + "b" * 64,
            target_fence_generation=1,
            demand_digest="c" * 64,
        ),
    )
    clock["at"] = AT + timedelta(seconds=3)
    with pytest.raises(ValueError, match="inverse current evidence source is unavailable"):
        await source.check(inv_mat)

    inv_source = replace(source, check_inverse=AsyncMock())
    await inv_source.check(inv_mat)

    # Revoke branch in HumanAccessCaseSource
    coord = await _coordinator()
    approved_rev = await _reviewed(coord.cases)
    await coord.cases.store.write_state(
        "action_promotion:ops.revoke-human-access",
        {"action_type": "ops.revoke-human-access", "mode": "enforce", "revision": 1},
    )
    rev_builder = HumanAccessMaterialBuilder(
        coord.cases, HumanAccessMaterialStore(coord.cases.store), groups
    )
    rev_plan = HumanAccessPlan(
        approved_rev.case_id,
        approved_rev.intent.subject.subject_id,
        "group:reader",
        HumanAccessOperation.REVOKE,
        "key:rev-source",
    )
    rev_action = Action.model_validate(
        {
            **raw_action,
            "action_id": "00000000-0000-0000-0000-000000000055",
            "action_type": "ops.revoke-human-access",
            "operation": "detach",
            "target_resource_ref": rev_plan.membership_lock_key.removeprefix("fdai:resource:"),
            "params": {
                "case_id": approved_rev.case_id,
                "expected_revision": approved_rev.revision,
                "replacement_revisions": {"primary": 7, "backup": 7},
            },
            "action_type_ref": {
                "kind": "action",
                "name": "ops.revoke-human-access",
                "version": "1.0.0",
                "catalog_digest": "sha256:" + "a" * 64,
            },
        }
    )
    rev_mat = await rev_builder.build(
        action=rev_action,
        promotion_record={
            "action_type": "ops.revoke-human-access",
            "mode": "enforce",
            "revision": 1,
        },
        at=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )
    rev_source = HumanAccessCaseSource(coord.cases, groups, promotions, lambda: clock["at"])
    await rev_source.check(rev_mat)
    await coord.cases.prepare_human_access(
        material=rev_mat, actor_ref="Muninn", now=AT + timedelta(seconds=1)
    )
    await rev_source.check(rev_mat)
