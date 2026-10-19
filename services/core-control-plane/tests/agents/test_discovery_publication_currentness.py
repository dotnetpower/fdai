"""Discovery withdrawal at actual Norns publication awaits, not just batch entry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fdai.agents import InMemoryBus, Norns, load_pantheon
from fdai.agents._framework import base
from fdai.agents._framework.rate_limiter import RateLimiter
from fdai.agents.norns import NornsCapacityError
from fdai.core.case_history import OperationalOutcomeClass

from tests.agents.test_operating_pattern_learning_e2e import (
    _learning_chain,
    _operational_input,
    _operational_raw,
)


async def queue_issue(norns: Norns, identity: str) -> None:
    await norns.on_typed_message(
        "object.issue",
        {
            "producer_principal": "Saga",
            "fingerprint": identity,
            "correlation_id": identity,
            "idempotency_key": identity,
        },
    )


async def test_withdrawal_after_budget_reservation_keeps_candidate_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enabled = [False]
    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(promotion_threshold=1)
    norns.bind_candidate_publication_gate(lambda: enabled[0])
    norns.bind_bus(bus)
    await queue_issue(norns, "budget-withdrawal")
    limiter = RateLimiter(per_minute=1, per_hour=1, now=lambda: 0.0)
    monkeypatch.setattr(norns, "_proposal_rate_limiter", lambda: limiter)
    reserve = base.reserve_proposal_budget

    async def withdraw(limiter: Any) -> Any:
        reservation = await reserve(limiter)
        enabled[0] = False
        return reservation

    enabled[0] = True
    monkeypatch.setattr(base, "reserve_proposal_budget", withdraw)
    assert await norns.flush_candidates() == 0
    assert not bus.messages_on("object.rule-candidate")
    assert len(norns.pending_candidates) == 1
    monkeypatch.setattr(base, "reserve_proposal_budget", reserve)
    enabled[0] = True
    assert await norns.flush_candidates() == 1
    assert len(bus.messages_on("object.rule-candidate")) == 1


async def test_transport_withdrawal_after_reservation_is_not_reported_as_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enabled = [False]
    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(promotion_threshold=1)
    norns.bind_candidate_publication_gate(lambda: enabled[0])
    norns.bind_bus(bus)
    await queue_issue(norns, "transport-withdrawal")
    limiter = RateLimiter(per_minute=1, per_hour=1, now=lambda: 0.0)
    monkeypatch.setattr(norns, "_proposal_rate_limiter", lambda: limiter)
    reserve = base.reserve_proposal_budget

    async def withdraw(limiter: Any) -> Any:
        reservation = await reserve(limiter)
        norns.bus = None
        return reservation

    monkeypatch.setattr(base, "reserve_proposal_budget", withdraw)
    enabled[0] = True
    assert await norns.flush_candidates() == 0
    assert len(norns.pending_candidates) == 1
    assert not bus.messages_on("object.rule-candidate")
    assert limiter.allow()


async def test_budget_release_failure_does_not_become_a_successful_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enabled = [False]
    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(promotion_threshold=1)
    norns.bind_candidate_publication_gate(lambda: enabled[0])
    norns.bind_bus(bus)
    await queue_issue(norns, "budget-release-failure")

    class BrokenReservation:
        async def commit(self) -> None:
            raise AssertionError("a held publication cannot commit budget")

        async def release(self) -> None:
            raise OSError("injected reservation release failure")

    async def withdraw(limiter: Any) -> BrokenReservation:
        enabled[0] = False
        return BrokenReservation()

    monkeypatch.setattr(base, "reserve_proposal_budget", withdraw)
    enabled[0] = True
    with pytest.raises(OSError, match="release failure"):
        await norns.flush_candidates()
    assert len(norns.pending_candidates) == 1
    assert not bus.messages_on("object.rule-candidate")


async def test_withdrawal_after_one_publication_stops_the_rest_of_the_batch() -> None:
    enabled = [False]

    class ClosingBus(InMemoryBus):
        async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
            await super().publish(principal, topic, payload)
            enabled[0] = False

    bus = ClosingBus(registry=load_pantheon())
    norns = Norns(promotion_threshold=1)
    norns.bind_candidate_publication_gate(lambda: enabled[0])
    norns.bind_bus(bus)
    await queue_issue(norns, "first-withdrawal")
    await queue_issue(norns, "second-withdrawal")
    enabled[0] = True
    assert await norns.flush_candidates() == 1
    assert len(bus.messages_on("object.rule-candidate")) == 1
    assert len(norns.pending_candidates) == 1


async def test_withdrawal_during_source_admission_blocks_later_publication() -> None:
    enabled = [False]
    gate_reads = [0]

    def gate() -> bool:
        gate_reads[0] += 1
        return enabled[0]

    class ClosingSource(Norns):
        async def _operational_candidate_cases_are_current(
            self, candidate: Mapping[str, Any]
        ) -> bool:
            current = await super()._operational_candidate_cases_are_current(candidate)
            if gate_reads[0]:
                enabled[0] = False
            return current

    bus = InMemoryBus(registry=load_pantheon())
    norns = ClosingSource(promotion_threshold=1)
    norns.bind_candidate_publication_gate(gate)
    norns.bind_bus(bus)
    await queue_issue(norns, "source-withdrawal")
    gate_reads[0] = 0
    enabled[0] = True
    assert await norns.flush_candidates() == 0
    assert not bus.messages_on("object.rule-candidate")
    assert len(norns.pending_candidates) == 1


async def test_withdrawal_after_pattern_ack_keeps_candidate_for_stable_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enabled = [False]
    bus, huginn, _muninn, norns, _mimir, _durable = _learning_chain()
    norns.bind_candidate_publication_gate(lambda: enabled[0])
    await huginn.ingest(
        _operational_raw("first", _operational_input("a", OperationalOutcomeClass.SUCCESS))
    )
    await huginn.ingest(
        _operational_raw("second", _operational_input("b", OperationalOutcomeClass.SUCCESS))
    )
    with pytest.raises(NornsCapacityError, match="retain for replay"):
        await huginn.ingest(
            _operational_raw("control", _operational_input("c", OperationalOutcomeClass.ROLLBACK))
        )
    assert not bus.messages_on("object.pattern")
    publish = bus.publish

    async def close_after_pattern(principal: str, topic: str, payload: dict[str, Any]) -> None:
        await publish(principal, topic, payload)
        if topic == "object.pattern":
            enabled[0] = False

    monkeypatch.setattr(bus, "publish", close_after_pattern)
    enabled[0] = True
    assert await norns.flush_candidates() == 0
    assert len(bus.messages_on("object.pattern")) == 1
    assert not bus.messages_on("object.rule-candidate")
    assert len(norns.pending_candidates) == 1
    enabled[0] = True
    assert await norns.flush_candidates() == 1
    assert len(bus.messages_on("object.pattern")) == 1
    assert len(bus.messages_on("object.rule-candidate")) == 1
