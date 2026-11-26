"""Original Action retention and atomic preparation, using the actual case coordinator."""

from __future__ import annotations

import runpy
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fdai.core.human_assignment import AssignmentCase, AssignmentCaseService, AssignmentState
from fdai.core.human_assignment.execution_material import (
    HumanAccessMaterialBuilder,
    HumanAccessMaterialStore,
)
from fdai.core.rbac.roles import Role
from fdai.shared.contracts.models import Action
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.human_access_execution import (
    HumanAccessExecutionMaterial,
    canonical_human_access_json,
)
from tests.core.human_assignment.test_access_apply import _ownership_merged

_support = runpy.run_path(
    str(
        Path(__file__).resolve().parents[5]
        / "packages/service-contracts/tests/test_human_access_execution.py"
    )
)
AT, sample = _support["AT"], _support["material"]


@pytest.fixture
async def fixture():
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    case = await _ownership_merged(cases)
    payload = sample().action().model_dump(mode="json")
    payload["params"] = {"case_id": case.case_id, "expected_revision": case.revision}
    from fdai_service_contracts.human_access import HumanAccessOperation, HumanAccessPlan

    plan = HumanAccessPlan(
        case.case_id,
        case.intent.subject.subject_id,
        "group:reader",
        HumanAccessOperation.GRANT,
        "key:sample",
    )
    payload["target_resource_ref"] = plan.membership_lock_key.removeprefix("fdai:resource:")
    action = Action.model_validate(payload)
    builder = HumanAccessMaterialBuilder(
        cases, HumanAccessMaterialStore(store), {Role.READER: "group:reader"}
    )
    material = await builder.build(
        action=action,
        promotion_record={"action_type": action.action_type, "mode": "enforce", "revision": 1},
        at=AT,
    )
    return store, cases, case, builder, material


async def test_material_uses_actual_reviewed_case_and_retains_original_action(fixture):
    _, cases, case, builder, material = fixture
    assert material.subject_id == case.intent.subject.subject_id
    assert material.requester_ref == case.intent.requester_ref
    assert await cases.get_case(case.case_id) == case
    assert await builder.materials.read(str(material.action().action_id)) == material


async def test_atomic_preparation_advances_r_to_r_plus_one_without_rewriting_action(fixture):
    _, cases, case, _, material = fixture
    original = material.action_json
    prepared = await cases.prepare_human_access(
        material=material, actor_ref="Muninn", now=AT + timedelta(seconds=5)
    )
    assert prepared.state is AssignmentState.IAM_APPLYING
    assert prepared.revision == case.revision + 1
    assert prepared.iam_preparation.material_digest == material.digest
    assert prepared.iam_preparation.source_case_digest == material.case_record_digest
    assert (
        material.action_json == original
        and material.action().params["expected_revision"] == case.revision
    )
    assert AssignmentCase.from_dict(prepared.to_dict()) == prepared
    assert (
        await cases.prepare_human_access(
            material=material, actor_ref="Muninn", now=AT + timedelta(seconds=6)
        )
        == prepared
    )


async def test_preparation_audit_failure_has_no_partial_case_binding(fixture, monkeypatch):
    store, cases, case, _, material = fixture
    monkeypatch.setattr(
        store,
        "compare_and_set_state_with_audit",
        AsyncMock(side_effect=RuntimeError("synthetic audit failure")),
    )
    with pytest.raises(RuntimeError, match="audit"):
        await cases.prepare_human_access(material=material, actor_ref="Muninn", now=AT)
    assert await cases.get_case(case.case_id) == case


async def test_preparation_does_not_accept_changed_source_or_expired_material(fixture):
    _, cases, case, _, material = fixture
    with pytest.raises(ValueError, match="expired"):
        await cases.prepare_human_access(
            material=material, actor_ref="Muninn", now=material.expires_at
        )
    await cases.mark_degraded(
        case_id=case.case_id,
        expected_revision=case.revision,
        reason_code="source_changed",
        actor_ref="Muninn",
        now=AT,
    )
    with pytest.raises(ValueError, match="source case"):
        await cases.prepare_human_access(material=material, actor_ref="Muninn", now=AT)


async def test_retained_material_rejects_original_action_rebinding(fixture):
    _, _, _, builder, material = fixture
    raw = material.action().model_dump(mode="json")
    raw["idempotency_key"] = "key:substituted"
    different = HumanAccessExecutionMaterial.model_validate(
        {**material.model_dump(), "action_json": canonical_human_access_json(raw)}
    )
    with pytest.raises(ValueError, match="different material"):
        await builder.materials.retain(different)


async def test_legacy_case_serialization_is_not_changed_by_absent_preparation(fixture):
    _, _, case, _, _ = fixture
    assert "iam_preparation" not in case.to_dict()
    assert AssignmentCase.from_dict(case.to_dict()) == case


async def test_material_store_and_builder_reject_invalid_inputs_and_support_revoke(
    fixture, monkeypatch
):
    from datetime import UTC, datetime

    from fdai.core.human_assignment.execution_material import MATERIAL_PREFIX
    from fdai_service_contracts.human_access import HumanAccessOperation, HumanAccessPlan
    from tests.core.human_assignment.test_revocation_delivery import _coordinator, _reviewed

    store, cases, case, builder, material = fixture

    # read() returns None when absent, and rejects inconsistent action_id
    assert await builder.materials.read("missing-id") is None
    await store.write_state(MATERIAL_PREFIX + "wrong-id", material.model_dump(mode="json"))
    with pytest.raises(ValueError, match="inconsistent"):
        await builder.materials.read("wrong-id")

    # build() rejects wrong action_type or created_at != at
    raw_action = material.action().model_dump(mode="json")
    with pytest.raises(ValueError, match="original current catalog Action"):
        await builder.build(
            action=Action.model_validate(
                {
                    **raw_action,
                    "action_type": "ops.other",
                    "action_type_ref": {**raw_action["action_type_ref"], "name": "ops.other"},
                }
            ),
            promotion_record={"action_type": "ops.other", "mode": "enforce"},
            at=AT,
        )
    with pytest.raises(ValueError, match="original current catalog Action"):
        await builder.build(
            action=Action.model_validate(raw_action),
            promotion_record={"action_type": raw_action["action_type"], "mode": "enforce"},
            at=AT + timedelta(seconds=1),
        )

    # build() rejects invalid case_id or expected_revision
    with pytest.raises(ValueError, match="exact current case arguments"):
        await builder.build(
            action=Action.model_validate(
                {**raw_action, "params": {"case_id": 123, "expected_revision": 1}}
            ),
            promotion_record={"action_type": raw_action["action_type"], "mode": "enforce"},
            at=AT,
        )
    with pytest.raises(ValueError, match="exact current case arguments"):
        await builder.build(
            action=Action.model_validate(
                {**raw_action, "params": {"case_id": case.case_id, "expected_revision": True}}
            ),
            promotion_record={"action_type": raw_action["action_type"], "mode": "enforce"},
            at=AT,
        )

    # build() returns retained prior when identical, or rejects rewritten action
    promo = {"action_type": raw_action["action_type"], "mode": "enforce", "revision": 1}
    assert await builder.build(action=material.action(), promotion_record=promo, at=AT) == material
    with pytest.raises(ValueError, match="MUST NOT be rewritten"):
        await builder.build(
            action=Action.model_validate({**raw_action, "idempotency_key": "key:rewritten"}),
            promotion_record=promo,
            at=AT,
        )

    # build() rejects promotion mismatch
    fresh_raw = {
        **raw_action,
        "action_id": "00000000-0000-0000-0000-000000000099",
    }
    with pytest.raises(ValueError, match="verified promotion source"):
        await builder.build(
            action=Action.model_validate(fresh_raw),
            promotion_record={"action_type": raw_action["action_type"], "mode": "shadow"},
            at=AT,
        )

    # build() detects case mutation during construction
    calls = 0
    orig_get = AssignmentCaseService.get_case

    async def mutating_get(self_svc: AssignmentCaseService, cid: str) -> AssignmentCase:
        nonlocal calls
        calls += 1
        res = await orig_get(self_svc, cid)
        if calls >= 3:
            from dataclasses import replace

            return replace(res, revision=res.revision + 1)
        return res

    monkeypatch.setattr(AssignmentCaseService, "get_case", mutating_get)
    with pytest.raises(ValueError, match="changed during material construction"):
        await builder.build(
            action=Action.model_validate(fresh_raw),
            promotion_record=promo,
            at=AT,
        )
    monkeypatch.setattr(AssignmentCaseService, "get_case", orig_get)

    # build() supports ops.revoke-human-access and rejects mismatched replacement_revisions
    coord = await _coordinator()
    approved_rev = await _reviewed(coord.cases)
    rev_builder = HumanAccessMaterialBuilder(
        coord.cases, HumanAccessMaterialStore(coord.cases.store), {Role.READER: "group:reader"}
    )
    rev_plan = HumanAccessPlan(
        approved_rev.case_id,
        approved_rev.intent.subject.subject_id,
        "group:reader",
        HumanAccessOperation.REVOKE,
        "key:revoke-sample",
    )
    rev_raw = {
        **raw_action,
        "action_id": "00000000-0000-0000-0000-000000000088",
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
    rev_promo = {"action_type": "ops.revoke-human-access", "mode": "enforce"}
    rev_mat = await rev_builder.build(
        action=Action.model_validate(rev_raw),
        promotion_record=rev_promo,
        at=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )
    assert rev_mat.action().action_type == "ops.revoke-human-access"

    bad_rev_raw = {
        **rev_raw,
        "action_id": "00000000-0000-0000-0000-000000000089",
        "params": {
            **rev_raw["params"],
            "replacement_revisions": {"primary": 99, "backup": 7},
        },
    }
    with pytest.raises(ValueError, match="replacement revisions differ"):
        await rev_builder.build(
            action=Action.model_validate(bad_rev_raw),
            promotion_record=rev_promo,
            at=datetime(2026, 9, 15, 12, tzinfo=UTC),
        )


def _make_fence(
    *,
    target_ref: str,
    sink_idempotency_key: str,
    resolved: bool = True,
    generation: int = 1,
    prior_resolved=None,
):
    from fdai.core.executor.idempotency_reservation import IdempotencyReservationIdentity
    from fdai.core.executor.lock_continuity import (
        EffectSinkContinuityPolicy,
        OwnershipContinuityStrategy,
    )
    from fdai.core.executor.target_dispatch_fence import (
        TargetDispatchFenceIdentity,
        TargetDispatchFenceRecord,
        resolve_target_fence_without_dispatch,
    )
    from fdai.shared.contracts.models import ExecutionPath
    from fdai.shared.providers.resource_lock import (
        ResourceLockAcquisitionReceipt,
        ResourceLockAcquisitionRequest,
    )

    at = AT + timedelta(seconds=generation)
    req = ResourceLockAcquisitionRequest.create(
        target_ref=target_ref,
        action_digest="sha256:" + str(generation) * 64,
        attempt=generation,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "b" * 40,
    )
    acq = ResourceLockAcquisitionReceipt.create(
        lock_key=req.lock_key,
        target_digest=req.target_digest,
        action_digest=req.action_digest,
        attempt=req.attempt,
        provider_id="postgres-advisory-lock",
        provider_version="1.0.0",
        producer_id=req.producer_id,
        producer_version=req.producer_version,
        owner_token_digest="sha256:" + "2" * 64,
        fencing_generation=None,
        session_identity=f"session:{generation}",
        provider_attestation_digest="sha256:" + "3" * 64,
        trust_anchor_id="postgres:primary",
        acquired_at=at,
        valid_until=None,
        source_revision=req.source_revision,
        request_digest=req.request_digest,
    )
    res_id = IdempotencyReservationIdentity.create(
        idempotency_key=sink_idempotency_key,
        action_digest=req.action_digest,
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint=str(generation) * 64,
        source_revision=req.source_revision,
        acquisition_receipt=acq,
    )
    policy = EffectSinkContinuityPolicy.create(
        sink_id="example-sink",
        sink_version="1.0.0",
        strategy=OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION,
        cancellation_supported=True,
        durable_unknown_quarantine=True,
        reconciliation_supported=True,
    )
    ident = TargetDispatchFenceIdentity.create(
        target_digest=acq.target_digest,
        reservation_identity=res_id,
        continuity_policy=policy,
        generation=generation,
        client_correlation_id=f"dispatch:{generation}",
        sink_idempotency_key=sink_idempotency_key,
    )
    prep = TargetDispatchFenceRecord.create_preparing(
        identity=ident, changed_at=at, prior_resolved_record=prior_resolved
    )
    if not resolved:
        return prep
    return resolve_target_fence_without_dispatch(
        prep, no_dispatch_evidence_digest="sha256:" + "8" * 64, changed_at=at
    )


async def test_recovery_source_inspect_binding_check_and_build(fixture, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace

    from fdai.core.human_assignment import DutyBinding
    from fdai.core.human_assignment.execution_recovery import HumanAccessRecoverySource
    from fdai.core.stewardship import Duty
    from fdai_service_contracts.human_access_recovery import membership_attempt_key

    store, cases, case, builder, material = fixture
    action = material.action()
    prefix = membership_attempt_key(action.idempotency_key)
    fence_holder = {
        "fence": _make_fence(
            target_ref=action.target_resource_ref,
            sink_idempotency_key=action.idempotency_key,
        )
    }
    fences = SimpleNamespace(read=AsyncMock(side_effect=lambda _t: fence_holder["fence"]))
    recovery = HumanAccessRecoverySource(builder, fences)

    # unacknowledged original mutation
    with pytest.raises(ValueError, match="unacknowledged"):
        await recovery.inspect(material)

    intent_data = {
        "action_digest": material.action_digest,
        "material_digest": material.digest,
        "target_digest": material.membership_plan().target_digest,
        "idempotency_key": action.idempotency_key,
        "before_membership": False,
    }
    result_data = {
        **intent_data,
        "owned_mutation": True,
        "outcome": "succeeded",
        "receipt_ref": "entra:receipt:1",
        "recorded_at": AT.isoformat(),
    }
    await store.write_state(prefix + ":intent", intent_data)
    await store.write_state(prefix + ":result", result_data)

    # unavailable fence
    saved_fence = fence_holder["fence"]
    fence_holder["fence"] = None
    with pytest.raises(ValueError, match="fence is unavailable"):
        await recovery.inspect(material)
    fence_holder["fence"] = saved_fence

    # incomplete demand page
    orig_page = store.read_state_page
    monkeypatch.setattr(store, "read_state_page", AsyncMock(return_value=([], 2)))
    with pytest.raises(ValueError, match="current demand is incomplete"):
        await recovery.inspect(material)
    monkeypatch.setattr(store, "read_state_page", orig_page)

    # binding errors: unchanged membership, unresolved fence, other demand
    await store.write_state(prefix + ":intent", {**intent_data, "before_membership": True})
    with pytest.raises(ValueError, match="not changed"):
        await recovery.binding(material)
    await store.write_state(prefix + ":intent", intent_data)

    fence_holder["fence"] = _make_fence(
        target_ref=action.target_resource_ref,
        sink_idempotency_key=action.idempotency_key,
        resolved=False,
    )
    with pytest.raises(ValueError, match="authoritative release closure"):
        await recovery.binding(material)
    fence_holder["fence"] = saved_fence

    # Add another degraded case for same subject and role -> other_demand=True
    other_case = replace(
        case,
        case_id="other-active-case",
        state=AssignmentState.DEGRADED,
        intent=replace(
            case.intent,
            idempotency_key="other-active-key",
            duty_bindings=(DutyBinding("Thor", Duty.BACKUP, "scope:platform"),),
        ),
    )
    await store.write_state("human_assignment:case:other-active-case", other_case.to_dict())
    with pytest.raises(ValueError, match="remains required by another assignment"):
        await recovery.binding(material)

    # If other case is a non-active state, it enters demand without blocking
    inactive_other = replace(other_case, state=AssignmentState.OWNERSHIP_MERGED)
    await store.write_state("human_assignment:case:other-active-case", inactive_other.to_dict())

    # Prepare and degrade the original case so recovery.build can succeed
    prepared = await cases.prepare_human_access(
        material=material, actor_ref="Muninn", now=AT + timedelta(seconds=1)
    )
    degraded = await cases.mark_degraded(
        case_id=case.case_id,
        expected_revision=prepared.revision,
        reason_code="effect_mismatch",
        actor_ref="Vidar",
        now=AT + timedelta(seconds=2),
    )

    inv_time = AT + timedelta(seconds=10)
    inv_raw = {
        **action.model_dump(mode="json"),
        "action_id": "00000000-0000-0000-0000-000000000077",
        "idempotency_key": "key:inverse-1",
        "action_type": "ops.revoke-human-access",
        "operation": "detach",
        "created_at": inv_time,
        "params": {
            "case_id": degraded.case_id,
            "expected_revision": degraded.revision,
            "recovery_of": str(action.action_id),
        },
        "action_type_ref": {
            "kind": "action",
            "name": "ops.revoke-human-access",
            "version": "1.0.0",
            "catalog_digest": "sha256:" + "a" * 64,
        },
    }
    inv_action = Action.model_validate(inv_raw)
    inv_promo = {"action_type": "ops.revoke-human-access", "mode": "enforce"}

    # build() rejects wrong group binding, non-degraded case, inconsistent promotion
    bad_group_recovery = HumanAccessRecoverySource(
        replace(builder, role_group_ids={Role.READER: "group:different"}), fences
    )
    with pytest.raises(ValueError, match="no longer the current role binding"):
        await bad_group_recovery.build(
            action=inv_action, original=material, promotion=inv_promo, at=inv_time
        )

    with pytest.raises(ValueError, match="exact held original case"):
        await recovery.build(
            action=Action.model_validate(
                {**inv_raw, "params": {**inv_raw["params"], "expected_revision": 999}}
            ),
            original=material,
            promotion=inv_promo,
            at=inv_time,
        )

    with pytest.raises(ValueError, match="inverse promotion source is inconsistent"):
        await recovery.build(
            action=inv_action,
            original=material,
            promotion={"action_type": "ops.revoke-human-access", "mode": "shadow"},
            at=inv_time,
        )

    # build() detects case mutation during construction
    get_calls = 0
    orig_get_case = AssignmentCaseService.get_case

    async def mutating_get_case(self_svc: AssignmentCaseService, cid: str) -> AssignmentCase:
        nonlocal get_calls
        res = await orig_get_case(self_svc, cid)
        if cid == degraded.case_id:
            get_calls += 1
            if get_calls >= 3:
                return replace(res, revision=res.revision + 1)
        return res

    monkeypatch.setattr(AssignmentCaseService, "get_case", mutating_get_case)
    with pytest.raises(ValueError, match="case changed during material construction"):
        await recovery.build(action=inv_action, original=material, promotion=inv_promo, at=inv_time)
    monkeypatch.setattr(AssignmentCaseService, "get_case", orig_get_case)

    # Successful build() and idempotent rebuild / rebound rejection
    inv_material = await recovery.build(
        action=inv_action, original=material, promotion=inv_promo, at=inv_time
    )
    assert inv_material.inverse is not None
    assert (
        await recovery.build(action=inv_action, original=material, promotion=inv_promo, at=inv_time)
        == inv_material
    )
    with pytest.raises(ValueError, match="Action was rebound"):
        await recovery.build(
            action=Action.model_validate({**inv_raw, "idempotency_key": "key:rebound"}),
            original=material,
            promotion=inv_promo,
            at=inv_time,
        )

    # Recursive invert is rejected
    with pytest.raises(ValueError, match="recursively invert"):
        await recovery.inspect(inv_material)

    # check() validations
    with pytest.raises(ValueError, match="binding is missing"):
        await recovery.check(material)

    await recovery.check(inv_material)

    # check() detects demand change when other_case becomes ACTIVE
    await store.write_state("human_assignment:case:other-active-case", other_case.to_dict())
    with pytest.raises(ValueError, match="membership demand changed"):
        await recovery.check(inv_material)

    # check() detects changed original material
    await store.write_state(
        "human_assignment:execution-material:" + str(action.action_id),
        {**material.model_dump(mode="json"), "case_record_digest": "f" * 64},
    )
    with pytest.raises(ValueError, match="original material changed"):
        await recovery.check(inv_material)
