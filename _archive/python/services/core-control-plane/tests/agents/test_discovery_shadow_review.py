from __future__ import annotations

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.agents.var import Var


def _bind() -> tuple[InMemoryBus, Norns, Saga, Var]:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    norns = Norns()
    saga = Saga()
    var = Var()
    for agent in (norns, saga, var):
        agent.bind_bus(bus)
    bus.subscribe("object.action-run", "Saga", saga.on_typed_message)
    bus.subscribe("object.audit-entry", "Norns", norns.on_typed_message)
    bus.subscribe("object.audit-entry", "Var", var.on_typed_message)
    bus.subscribe("object.approval", "Norns", norns.on_typed_message)
    bus.subscribe("object.approval", "Saga", saga.on_typed_message)
    return bus, norns, saga, var


async def test_human_shadow_review_upgrades_one_sample_without_counting_it_twice() -> None:
    bus, norns, _, var = _bind()
    await bus.publish(
        "Thor",
        "object.action-run",
        {
            "producer_principal": "Thor",
            "correlation_id": "shadow-1",
            "idempotency_key": "shadow-1:succeeded",
            "action_type": "remediate.enable-tde",
            "resource_id": "resource-1",
            "state": "succeeded",
            "shadow_mode": True,
            "terminal_at": "2026-08-29T01:00:00Z",
            "initiator_principal": "operator-a",
            "policy_escape": True,
        },
    )

    before = norns.shadow_dwell_evidence("remediate.enable-tde")
    assert before is not None
    assert before.sample_size == 1
    assert before.reviewed_count == 0
    assert before.policy_escapes == 1
    assert len(var.pending_shadow_reviews()) == 1

    approval = await var.decide_shadow_review(
        "shadow-1",
        reviewer="operator-b",
        agreed=True,
    )

    assert approval is not None
    after = norns.shadow_dwell_evidence("remediate.enable-tde")
    assert after is not None
    assert after.sample_size == 1
    assert after.reviewed_count == 1
    assert after.agreed_count == 1
    assert after.policy_escapes == 1
    assert var.pending_shadow_reviews() == ()
    review_audits = [
        message.payload
        for message in bus.messages_on("object.audit-entry")
        if message.payload.get("shadow_review_update") is True
    ]
    assert len(review_audits) == 1
    assert review_audits[0]["operator_reviewed"] is True
    assert review_audits[0]["policy_escape"] is True


async def test_shadow_review_rejects_the_action_initiator() -> None:
    bus, _, _, var = _bind()
    await bus.publish(
        "Thor",
        "object.action-run",
        {
            "producer_principal": "Thor",
            "correlation_id": "shadow-2",
            "idempotency_key": "shadow-2:succeeded",
            "action_type": "remediate.enable-rbac",
            "resource_id": "resource-2",
            "state": "succeeded",
            "shadow_mode": True,
            "terminal_at": "2026-08-29T02:00:00Z",
            "initiator_principal": "operator-a",
            "policy_escape": False,
        },
    )

    with pytest.raises(ValueError, match="cannot review their own"):
        await var.decide_shadow_review("shadow-2", reviewer="Operator-A", agreed=True)
