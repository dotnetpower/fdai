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
