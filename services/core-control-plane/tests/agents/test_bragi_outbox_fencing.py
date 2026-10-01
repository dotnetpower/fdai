"""Bragi turn and publication outboxes follow the fenced durable publication contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.bragi_models import ConversationSession, RoutingDecision, Turn
from fdai.agents._framework.bragi_publication import (
    _claim_publication,
    _mark_publication_published,
    _publication_key,
    _reset_publication_pending,
)
from fdai.agents._framework.bragi_runtime_helpers import _turn_outbox_key
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), handler_timeout=None)


class _FailingTurnBus(InMemoryBus):
    def __init__(self, failing_turn_indexes: set[int]) -> None:
        super().__init__(registry=load_pantheon(), handler_timeout=None)
        self.failing_turn_indexes = set(failing_turn_indexes)

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.turn" and payload.get("turn_index") in self.failing_turn_indexes:
            raise RuntimeError("transient turn publication failure")
        await super().publish(principal, topic, payload)


def _turn(index: int) -> Turn:
    return Turn(
        turn_index=index,
        question=f"question {index}",
        primary_agent="Bragi",
        answer={"trace_ref": f"corr-turn-{index}", "body": "ok"},
        decision=RoutingDecision(
            primary_agent="Bragi",
            scores={},
            tie_break=None,
            method="deterministic",
            semantic_score=None,
            semantic_margin=None,
            provider_status="not_configured",
        ),
    )


def _handoff(index: int) -> dict[str, Any]:
    return {
        "producer_principal": "Bragi",
        "correlation_id": f"handoff-fence-{index}",
        "idempotency_key": f"handoff:fence:{index}",
        "reason": "operator_handoff",
    }


async def test_turn_late_publisher_cannot_mark_or_reopen_a_reclaimed_claim() -> None:
    now = datetime(2032, 1, 1, tzinfo=UTC)
    store = InMemoryStateStore()
    bragi = Bragi(state_store=store, clock=lambda: now)
    session = ConversationSession(session_id="fence", user_id="operator")
    payload = await bragi._checkpoint_turn_payload(session=session, turn=_turn(0))  # noqa: SLF001

    first = await bragi._claim_turn_publication(payload)  # noqa: SLF001
    assert first is not None
    now += timedelta(minutes=6)
    second = await bragi._claim_turn_publication(payload)  # noqa: SLF001
    assert second is not None
    assert second.owner != first.owner

    await bragi._reset_turn_publication_pending(payload, first)  # noqa: SLF001
    key = _turn_outbox_key(str(payload["session_ref"]), int(payload["turn_index"]))
    stored = await store.read_state(key)
    assert stored is not None
    assert stored["status"] == "publishing"
    assert stored["claim_owner"] == second.owner

    assert await bragi._mark_turn_published(payload, first) is False  # noqa: SLF001
    assert await bragi._mark_turn_published(payload, second) is True  # noqa: SLF001
    assert (await store.read_state(key))["status"] == "published"


async def test_publication_late_publisher_cannot_mark_or_reopen_a_reclaimed_claim() -> None:
    now = datetime(2032, 1, 1, tzinfo=UTC)
    store = InMemoryStateStore()
    bragi = Bragi(state_store=store, clock=lambda: now)
    payload = _handoff(0)
    assert await bragi.publish_handoff_event(dict(payload)) is False
    key = _publication_key(payload)

    first = await _claim_publication(store, payload, now=now)
    assert first is not None
    later = now + timedelta(minutes=6)
    second = await _claim_publication(store, payload, now=later)
    assert second is not None
    assert second.owner != first.owner

    await _reset_publication_pending(store, payload, first)
    stored = await store.read_state(key)
    assert stored is not None
    assert stored["status"] == "publishing"
    assert stored["claim_owner"] == second.owner

    assert await _mark_publication_published(store, payload, first) is False
    assert await _mark_publication_published(store, payload, second) is True
    assert (await store.read_state(key))["status"] == "published"


async def test_turn_recovery_defers_a_failed_row_and_publishes_the_rest() -> None:
    store = InMemoryStateStore()
    checkpoint = Bragi(state_store=store)
    session = ConversationSession(session_id="defer", user_id="operator")
    payloads = [
        await checkpoint._checkpoint_turn_payload(session=session, turn=_turn(index))  # noqa: SLF001
        for index in range(3)
    ]
    restarted = Bragi(state_store=store)
    bus = _FailingTurnBus({1})
    restarted.bind_bus(bus)

    progress, published = await restarted.recover_state()

    assert progress == 0
    assert published == 2
    published_indexes = {
        message.payload["turn_index"] for message in bus.messages_on("object.turn")
    }
    assert published_indexes == {0, 2}
    failed = await store.read_state(
        _turn_outbox_key(str(payloads[1]["session_ref"]), int(payloads[1]["turn_index"]))
    )
    assert failed is not None
    assert failed["status"] == "pending"
    assert failed["payload"]["idempotency_key"] == payloads[1]["idempotency_key"]
    assert restarted._turn_outbox_pending == 1  # noqa: SLF001
    assert restarted.behavior_snapshot().get("turn_outbox:recovery_publish_failed") == 1


async def test_turn_recovery_skips_a_malformed_row_without_aborting() -> None:
    store = InMemoryStateStore()
    checkpoint = Bragi(state_store=store)
    session = ConversationSession(session_id="malformed", user_id="operator")
    await checkpoint._checkpoint_turn_payload(session=session, turn=_turn(0))  # noqa: SLF001
    malformed_key = "pantheon/bragi/turn-outbox/malformed/00000000000000000000"
    await store.write_state(
        malformed_key,
        {"schema_version": "1.0.0", "revision": 1, "status": "pending", "payload": "bad"},
    )
    restarted = Bragi(state_store=store)
    bus = _bus()
    restarted.bind_bus(bus)

    _progress, published = await restarted.recover_state()

    assert published == 1
    assert len(bus.messages_on("object.turn")) == 1
    assert (await store.read_state(malformed_key))["status"] == "pending"
    assert restarted.behavior_snapshot().get("turn_outbox:recovery_invalid_row") == 1


async def test_publication_recovery_defers_failure_and_skips_malformed_row() -> None:
    store = InMemoryStateStore()
    checkpoint = Bragi(state_store=store)
    for index in range(2):
        assert await checkpoint.publish_handoff_event(_handoff(index)) is False
    await store.write_state(
        "pantheon/bragi/publication-outbox/malformed",
        {"schema_version": "1.0.0", "revision": 1, "status": "pending", "topic": "object.other"},
    )

    class _FailFirstHandoff(InMemoryBus):
        def __init__(self) -> None:
            super().__init__(registry=load_pantheon(), handler_timeout=None)

        async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
            if payload.get("idempotency_key") == "handoff:fence:0":
                raise RuntimeError("transient handoff failure")
            await super().publish(principal, topic, payload)

    restarted = Bragi(state_store=store)
    bus = _FailFirstHandoff()
    restarted.bind_bus(bus)

    assert await restarted.recover_bragi_publications() == 1
    assert [m.payload["idempotency_key"] for m in bus.messages_on("object.handoff-escalation")] == [
        "handoff:fence:1"
    ]
    assert (await store.read_state(_publication_key(_handoff(0))))["status"] == "pending"
    behaviors = restarted.behavior_snapshot()
    assert behaviors.get("publication_outbox:recovery_publish_failed") == 1
    assert behaviors.get("publication_outbox:recovery_invalid_row") == 1


async def test_maintenance_redrives_deferred_turn_and_publication_rows() -> None:
    store = InMemoryStateStore()
    bragi = Bragi(state_store=store)
    session = ConversationSession(session_id="redrive", user_id="operator")
    await bragi._checkpoint_turn_payload(session=session, turn=_turn(0))  # noqa: SLF001
    assert await bragi.publish_handoff_event(_handoff(9)) is False
    bus = _bus()
    bragi.bind_bus(bus)

    await bragi.maintenance_tick()

    assert len(bus.messages_on("object.turn")) == 1
    assert len(bus.messages_on("object.handoff-escalation")) == 1
    assert bragi._turn_outbox_pending == 0  # noqa: SLF001
