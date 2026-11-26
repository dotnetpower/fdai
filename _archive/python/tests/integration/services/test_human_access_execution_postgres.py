"""Actual role-separated SQL material, HIL decisions and preparation readback on task-only DBs."""

from __future__ import annotations

import runpy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import psycopg
import pytest
from fdai.core.human_assignment import AssignmentCaseService
from fdai.core.human_assignment.execution_approval import HumanAccessApprovalService
from fdai.core.human_assignment.execution_material import (
    HumanAccessMaterialBuilder,
    HumanAccessMaterialStore,
)
from fdai.core.human_assignment.execution_sources import (
    HumanAccessCaseSource,
    HumanAccessCurrentPublisher,
)
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.shared.contracts.models import Action, Mode
from fdai_executor_service.adapters.postgres_human_access import PostgresHumanAccessSource
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreConfig
from fdai_operator_service.postgres_hil_decision import (
    PostgresHilDecisionPermissionError,
    PostgresHilDecisionStore,
)
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.human_access import HumanAccessOperation, HumanAccessPlan

ROOT = Path(__file__).resolve().parents[3]
_ownership_merged = runpy.run_path(
    str(ROOT / "services/core-control-plane/tests/core/human_assignment/test_access_apply.py")
)["_ownership_merged"]
_support = runpy.run_path(str(Path(__file__).with_name("test_assignment_receipt_postgres.py")))
database, _role = _support["database"], _support["_role"]
_contract = runpy.run_path(
    str(ROOT / "packages/service-contracts/tests/test_human_access_execution.py")
)
pytestmark = pytest.mark.integration


def install(database):
    with psycopg.connect(database) as connection:
        connection.execute(
            """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_executor')
            THEN CREATE ROLE fdai_executor NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$;
            GRANT USAGE ON SCHEMA public TO fdai_executor;"""
        )
        for path in [
            "core-control-plane/versions/20260910_core_target_dispatch_fence.py",
            "core-control-plane/versions/20260915_core_human_access_execution.py",
            "isolated-executor/versions/20260915_executor_human_access_read.py",
        ]:
            statements = []
            with patch("alembic.op.execute", side_effect=statements.append):
                runpy.run_path(str(ROOT / "service-migrations/branches" / path))["upgrade"]()
            for statement in statements:
                connection.execute(statement)


async def ready(database):
    install(database)
    at = datetime.now(UTC)
    core = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_role(database, "fdai_core")))
    cases = AssignmentCaseService(core)
    case = await _ownership_merged(cases)
    role_groups = {"Reader": "group:reader"}
    plan = HumanAccessPlan(
        case.case_id,
        case.intent.subject.subject_id,
        role_groups["Reader"],
        HumanAccessOperation.GRANT,
        "key:sample",
    )
    payload = _contract["material"]().action().model_dump(mode="json")
    payload.update(
        created_at=at.isoformat(),
        params={"case_id": case.case_id, "expected_revision": case.revision},
        target_resource_ref=plan.membership_lock_key.removeprefix("fdai:resource:"),
    )
    action = Action.model_validate(payload)
    promotion = {"action_type": action.action_type, "mode": "enforce", "revision": 1}
    await core.write_state("action_promotion:" + action.action_type, promotion)
    builder = HumanAccessMaterialBuilder(
        cases, HumanAccessMaterialStore(core), {Role.READER: role_groups["Reader"]}
    )
    material = await builder.build(action=action, promotion_record=promotion, at=at)
    source = HumanAccessCaseSource(
        cases,
        builder.role_group_ids,
        SimpleNamespace(refresh=AsyncMock(), mode_of=lambda _: Mode.ENFORCE),
        lambda: at,
    )
    approvals = HumanAccessApprovalService(
        core,
        SimpleNamespace(is_current_owner=AsyncMock(return_value=True)),
        source.check,
        lambda: at,
        lambda _person, _action: True,
    )
    await approvals.park(material)
    operator = PostgresHilDecisionStore(
        PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )

    async def decide(actor="owner:independent", roles=frozenset({OperatorRole.OWNER})):
        approval_id = material.approval_ids[0]
        return await operator.append_hil_decision(
            approval_id=approval_id,
            idempotency_key=f"human-access:{approval_id}",
            action_hash=material.digest,
            decision="approve",
            approver_oid=actor,
            approver_roles=roles,
            justification="Synthetic independent current execution review.",
            decided_at=at,
            expected_expires_at=material.expires_at,
            expected_submitter_oid=material.requester_ref,
            expected_decision_route="human_access",
            expected_required_role="Owner",
        )

    return SimpleNamespace(
        material=material,
        builder=builder,
        source=source,
        core=core,
        cases=cases,
        approvals=approvals,
        publisher=HumanAccessCurrentPublisher(source, approvals, lambda: at),
        decide=decide,
        at=at,
        executor=PostgresHumanAccessSource(_role(database, "fdai_executor"), role_groups),
    )


async def prepared(database):
    f = await ready(database)
    await f.decide()
    await f.cases.prepare_human_access(material=f.material, actor_ref="Muninn", now=f.at)
    await f.publisher.observe(f.material)
    return f


async def test_actual_hil_decision_preparation_and_exact_executor_source(database):
    f = await prepared(database)
    assert (
        await f.executor.material_for(
            action_id=f.material.action().action_id, action_digest=f.material.action_digest
        )
        == f.material
    )
    current = await f.executor.current(f.material)
    assert current.refusal(f.material, now=f.at) is None
    assert current.approvals[0].approver_ref == "owner:independent"
    assert current.current_case_revision == f.material.action().params["expected_revision"] + 1


@pytest.mark.parametrize(
    "actor,roles",
    [
        ("target-1", {OperatorRole.OWNER}),
        ("requester-1", {OperatorRole.OWNER}),
        ("owner:independent", {OperatorRole.APPROVER}),
    ],
)
async def test_actual_operator_commit_refuses_target_requester_and_non_owner(
    database, actor, roles
):
    f = await ready(database)
    with pytest.raises(PostgresHilDecisionPermissionError):
        await f.decide(actor, frozenset(roles))


async def test_executor_wrong_digest_gets_no_private_material_and_cannot_write_case(database):
    f = await prepared(database)
    assert (
        await f.executor.material_for(
            action_id=f.material.action().action_id, action_digest="sha256:" + "f" * 64
        )
        is None
    )
    with psycopg.connect(_role(database, "fdai_executor")) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "UPDATE state_kv SET value='{}' WHERE key=%s",
                ("human_assignment:case:" + f.material.action().params["case_id"],),
            )


async def test_promotion_revocation_invalidates_retained_positive_snapshot(database):
    f = await prepared(database)
    await f.core.write_state(
        "action_promotion:" + f.material.action().action_type,
        {"action_type": f.material.action().action_type, "mode": "shadow", "revision": 2},
    )
    with pytest.raises(ValueError, match="promotion"):
        await f.executor.current(f.material)


@pytest.mark.parametrize("state", [{"engaged": True}, {"engaged": 0}, {}])
async def test_current_kill_switch_invalidates_retained_executor_snapshot(database, state):
    f = await prepared(database)
    await f.core.write_state("system:kill-switch", state)
    with pytest.raises(ValueError, match="emergency halt"):
        await f.executor.current(f.material)


async def test_same_revision_case_field_change_cannot_reuse_preparation(database):
    f = await prepared(database)
    key = "human_assignment:case:" + f.material.action().params["case_id"]
    value = dict(await f.core.read_state(key))
    value["intent"]["justification"] = "A different unreviewed retained intent."
    await f.core.write_state(key, value)
    with pytest.raises(ValueError, match="outside the exact source transition"):
        await f.executor.current(f.material)


async def test_retained_material_is_immutable_even_for_core_and_role_is_enforced(database):
    f = await prepared(database)
    key = "human_assignment:execution-material:" + str(f.material.action().action_id)
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        await f.core.write_state(key, {"changed": True})
    admin = PostgresHumanAccessSource(database, {"Reader": "group:reader"})
    with pytest.raises(PermissionError, match="Executor role"):
        await admin.material_for(
            action_id=f.material.action().action_id, action_digest=f.material.action_digest
        )


async def prepared_revocation(database):
    install(database)
    revoked = runpy.run_path(
        str(ROOT / "services/core-control-plane/tests/core/human_assignment/test_revocation.py")
    )
    replacement = runpy.run_path(
        str(ROOT / "services/core-control-plane/tests/core/human_assignment/test_replacement.py")
    )
    core = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_role(database, "fdai_core")))
    cases = await revoked["_cases"](core)
    for case in (
        replacement["_active"]("primary", "human:new"),
        replacement["_active"]("backup", "human:backup", Duty.BACKUP),
    ):
        await core.write_state("human_assignment:case:" + case.case_id, case.to_dict())
    case = await revoked["_reviewed"](cases)
    at = datetime.now(UTC)
    plan = HumanAccessPlan(
        case.case_id,
        case.intent.subject.subject_id,
        "group:reader",
        HumanAccessOperation.REVOKE,
        "key:removal",
    )
    payload = _contract["material"](revoke=True).action().model_dump(mode="json")
    payload.update(
        created_at=at.isoformat(),
        params={
            "case_id": case.case_id,
            "expected_revision": case.revision,
            "replacement_revisions": dict(case.intent.revocation.replacement_revisions),
        },
        target_resource_ref=plan.membership_lock_key.removeprefix("fdai:resource:"),
    )
    action = Action.model_validate(payload)
    promotion = {"action_type": action.action_type, "mode": "enforce", "revision": 1}
    await core.write_state("action_promotion:" + action.action_type, promotion)
    builder = HumanAccessMaterialBuilder(
        cases, HumanAccessMaterialStore(core), {Role.READER: "group:reader"}
    )
    material = await builder.build(action=action, promotion_record=promotion, at=at)
    source = HumanAccessCaseSource(
        cases,
        builder.role_group_ids,
        SimpleNamespace(refresh=AsyncMock(), mode_of=lambda _: Mode.ENFORCE),
        lambda: at,
    )
    approvals = HumanAccessApprovalService(
        core,
        SimpleNamespace(is_current_owner=AsyncMock(return_value=True)),
        source.check,
        lambda: at,
        lambda _p, _a: True,
    )
    await approvals.park(material)
    operator = PostgresHilDecisionStore(
        PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    slot = material.approval_ids[0]
    await operator.append_hil_decision(
        approval_id=slot,
        idempotency_key="human-access:" + slot,
        action_hash=material.digest,
        decision="approve",
        approver_oid="human:independent-execution-reviewer",
        approver_roles=frozenset({OperatorRole.OWNER}),
        justification="Synthetic separately reviewed removal.",
        decided_at=at,
        expected_expires_at=material.expires_at,
        expected_submitter_oid=material.requester_ref,
        expected_decision_route="human_access",
        expected_required_role="Owner",
    )
    await cases.prepare_human_access(material=material, actor_ref="Muninn", now=at)
    await HumanAccessCurrentPublisher(source, approvals, lambda: at).observe(material)
    return SimpleNamespace(
        core=core,
        material=material,
        cases=cases,
        executor=PostgresHumanAccessSource(
            _role(database, "fdai_executor"), {"Reader": "group:reader"}
        ),
    )


async def test_actual_revocation_source_joins_exact_original_hold_and_replacements(database):
    f = await prepared_revocation(database)
    assert (await f.executor.current(f.material)).current_case_state == "iam_applying"


@pytest.mark.parametrize(
    "change",
    ["backup_lost", "original_revision", "same_person", "other_demand", "malformed_receipt"],
)
async def test_actual_revocation_rechecks_changed_replacements_original_and_demand(
    database, change
):
    f = await prepared_revocation(database)
    key = "human_assignment:case:" + ("old" if change == "original_revision" else "backup")
    value = dict(await f.core.read_state(key))
    if change == "backup_lost":
        value["state"] = "degraded"
        value["degraded_reason"] = "source_lost"
    elif change == "original_revision":
        value["revision"] += 1
    elif change == "same_person":
        value["intent"]["subject"]["subject_id"] = "human:new"
    elif change == "malformed_receipt":
        value["effect_receipts"] = [{"kind": "iam"}, {"kind": "ownership"}]
    else:
        key = "human_assignment:case:other-demand"
        value.update(case_id="other-demand")
        value["intent"]["subject"]["subject_id"] = f.material.subject_id
    await f.core.write_state(key, value)
    with pytest.raises(ValueError):
        await f.executor.current(f.material)
