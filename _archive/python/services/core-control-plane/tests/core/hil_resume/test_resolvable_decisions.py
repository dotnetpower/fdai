"""Only a terminal decision may change a park; a pending or unknown value changes nothing.

Core refuses such a decision before it reads the park, the dispatch path separately requires an
approval that cleared the delegation gate, and the HIL decision consumer dead-letters every value
other than approve or reject.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fdai.core.hil_resume import ResolveOutcome
from fdai.core.hil_resume import coordinator as coordinator_module
from fdai.runtime.consumers import _consume_hil_decisions
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.testing import InMemoryEventBus

from tests.core.hil_resume.development_category_harness import CategoryScenario
from tests.core.hil_resume.test_coordinator import _APPROVER, _audit_kinds, _coordinator, _park

UNRESOLVABLE: tuple[Any, ...] = (HilDecision.PENDING, "pending", "unknown", "", None, ["approve"])
UNPRIVILEGED = "someone-without-any-role"


@pytest.mark.parametrize("decision", UNRESOLVABLE)
async def test_an_ordinary_park_refuses_a_decision_that_cannot_resolve_it(decision: Any) -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-pending")
    before = await store.read_state("hil_park:aid-pending")

    result = await coordinator.resolve(
        approval_id="aid-pending", decision=decision, approver_oid=_APPROVER
    )

    assert (result.outcome, result.reason) == (
        ResolveOutcome.DECISION_REFUSED,
        "decision_not_resolvable",
    )
    assert await store.read_state("hil_park:aid-pending") == before
    assert publisher.records == ()
    assert "hil.resolve.decision_refused" in _audit_kinds(store)
    assert not any(kind.startswith("hil.approved") for kind in _audit_kinds(store))


async def test_a_tampered_park_is_not_closed_by_an_unresolvable_decision() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-tampered")
    parked = await store.read_state("hil_park:aid-tampered")
    assert parked is not None
    parked["action"]["target_resource_ref"] = "azure://resource/changed"
    await store.write_state("hil_park:aid-tampered", parked)

    result = await coordinator.resolve(
        approval_id="aid-tampered", decision=HilDecision.PENDING, approver_oid=_APPROVER
    )

    # The refusal precedes the integrity check, which would otherwise close the park.
    assert result.outcome is ResolveOutcome.DECISION_REFUSED
    assert await store.read_state("hil_park:aid-tampered") == parked
    assert "hil.resolve.integrity_failed" not in _audit_kinds(store)
    assert publisher.records == ()


@pytest.mark.parametrize("decision", UNRESOLVABLE)
async def test_an_owner_only_park_refuses_a_decision_that_cannot_resolve_it(
    decision: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = CategoryScenario()
    await scenario.request()
    parked = await scenario.parked()
    scenario.record_dispatch(monkeypatch)

    result = await scenario.coordinator.resolve(
        approval_id=str(parked["approval_id"]),
        decision=decision,
        approver_oid=UNPRIVILEGED,
        approver_can_approve_hil=False,
    )

    assert result.outcome is ResolveOutcome.DECISION_REFUSED
    assert await scenario.store.read_state(f"hil_park:{parked['approval_id']}") == parked
    assert scenario.dispatched == []
    assert scenario.audits("hil.resolve.development_self_approval") == []


async def test_dispatch_requires_an_admitted_approval_even_past_the_first_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-bypass")
    before = await store.read_state("hil_park:aid-bypass")
    # A regression in the first guard must still meet the dispatch guard.
    monkeypatch.setattr(coordinator_module, "resolvable_decision", lambda decision: decision)

    result = await coordinator.resolve(
        approval_id="aid-bypass", decision=HilDecision.PENDING, approver_oid=_APPROVER
    )

    assert (result.outcome, result.reason) == (
        ResolveOutcome.DECISION_REFUSED,
        "approval_not_admitted",
    )
    assert await store.read_state("hil_park:aid-bypass") == before
    assert publisher.records == ()
    assert "hil.resolve.dispatch_refused" in _audit_kinds(store)


async def test_the_consumer_dead_letters_a_pending_decision_for_an_owner_only_park(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = CategoryScenario()
    await scenario.request()
    parked = await scenario.parked()
    approval_id = str(parked["approval_id"])
    scenario.record_dispatch(monkeypatch)
    bus = InMemoryEventBus()
    for decision in ("pending", "timeout", "bogus"):
        await bus.publish(
            "hil-decisions",
            approval_id,
            {"approval_id": approval_id, "decision": decision, "approver_oid": UNPRIVILEGED},
        )

    await _consume_hil_decisions(
        bus=bus,
        topic="hil-decisions",
        coordinator=scenario.coordinator,
        stop=asyncio.Event(),
    )

    dead = [envelope.payload async for envelope in bus.subscribe("hil-decisions.dlq", "test")]
    assert [item["payload"]["decision"] for item in dead] == ["pending", "timeout", "bogus"]
    assert {item["reason"] for item in dead} == {"hil_decision_consume_error:ValueError"}
    assert scenario.dispatched == []
    assert await scenario.store.read_state(f"hil_park:{approval_id}") == parked
    assert not [
        item
        for item in scenario.store.audit_entries
        if str(item["entry"].get("action_kind", "")).startswith(("hil.resolve", "hil.approved"))
    ]
