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
