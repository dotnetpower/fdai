"""Core ingress tests for Operator-to-Bragi post-turn review requests."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from fdai.agents import PantheonRuntime
from fdai.core.learning import (
    PostTurnReviewInput,
    PostTurnReviewState,
    review_input_to_mapping,
)
from fdai.core.operator_memory import InMemoryOperatorMemoryStore
from fdai.delivery.post_turn_review_ingress import PostTurnReviewRequestConsumer
from fdai.runtime.post_turn_review import build_post_turn_review_runtime
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.post_turn_review import (
    POST_TURN_REVIEW_REQUEST_TOPIC,
    POST_TURN_REVIEW_TOPIC,
    PostTurnReviewInputWire,
    post_turn_review_request_payload,
)

NOW = datetime(2026, 9, 29, 1, tzinfo=UTC)


def _review_input() -> PostTurnReviewInput:
    return PostTurnReviewInput(
        review_id="review-ingress-1",
        principal_scope="principal-ingress-1",
        operator_turn_id="operator-turn-1",
        assistant_turn_id="assistant-turn-1",
        completed_at=NOW,
        operator_body="Inspect the bounded evidence.",
        assistant_body="Inspection completed.",
        explicit_corrections=("Use the scoped query next time.",),
        evidence_refs=("audit:1",),
    )


def _request_envelope(payload: dict[str, object] | None = None) -> EventEnvelope:
    request_payload = payload or post_turn_review_request_payload(
        PostTurnReviewInputWire.model_validate(review_input_to_mapping(_review_input()))
    )
    return EventEnvelope(
        topic=POST_TURN_REVIEW_REQUEST_TOPIC,
        key="operator-post-turn-review:review-ingress-1",
        payload=request_payload,
        offset=None,
    )


async def test_core_ingress_republishes_once_through_bragi_and_duplicate_is_terminal_once() -> None:
    bus = InMemoryEventBus()
    runtime = build_post_turn_review_runtime(
        state_store=InMemoryStateStore(),
        operator_memory=InMemoryOperatorMemoryStore(),
        now=lambda: NOW,
    )
    pantheon = PantheonRuntime.build(
        provider=bus,
        raw_event_topic="runtime.raw-events",
        post_turn_review=runtime.coordinator,
    )
    consumer = PostTurnReviewRequestConsumer(pantheon)
    envelope = _request_envelope()

    assert await consumer.handle(bus=bus, envelope=envelope) is True
    assert await consumer.handle(bus=bus, envelope=envelope) is True

    published = [event async for event in bus.subscribe(POST_TURN_REVIEW_TOPIC, "assert-bragi")]
    assert len(published) == 1
    assert published[0].payload["producer_principal"] == "Bragi"

    run_task = asyncio.create_task(pantheon.run())
    try:
        for _ in range(50):
            records = await runtime.reviews.list()
            if records:
                break
            await asyncio.sleep(0.05)
    finally:
        await pantheon.stop()
        run_task.cancel()
        with suppress(asyncio.CancelledError):
            await run_task

    records = await runtime.reviews.list()
    assert len([record for record in records if record.review_id == "review-ingress-1"]) == 1
    assert records[0].state is PostTurnReviewState.ABSTAINED


async def test_core_ingress_dead_letters_malformed_request() -> None:
    bus = InMemoryEventBus()
    pantheon = PantheonRuntime.build(provider=bus, raw_event_topic="runtime.raw-events")
    consumer = PostTurnReviewRequestConsumer(pantheon)

    accepted = await consumer.handle(
        bus=bus,
        envelope=_request_envelope({"kind": "post_turn_review_request"}),
    )

    assert accepted is False
    assert [event async for event in bus.subscribe(POST_TURN_REVIEW_TOPIC, "assert-empty")] == []
    dlq = [
        event async for event in bus.subscribe(f"{POST_TURN_REVIEW_REQUEST_TOPIC}.dlq", "assert")
    ]
    assert len(dlq) == 1
    assert dlq[0].payload["reason"] == "invalid_post_turn_review_request"


async def test_core_ingress_missing_bragi_fails_closed_without_publish() -> None:
    bus = InMemoryEventBus()
    consumer = PostTurnReviewRequestConsumer(_NoBragiRuntime())

    accepted = await consumer.handle(bus=bus, envelope=_request_envelope())

    assert accepted is False
    assert [event async for event in bus.subscribe(POST_TURN_REVIEW_TOPIC, "assert-empty")] == []


class _NoBragiRuntime:
    agents: dict[str, Any] = {}


async def test_core_ingress_dead_letters_a_failed_bragi_publish_without_stopping() -> None:
    bus = InMemoryEventBus()
    consumer = PostTurnReviewRequestConsumer(_FailingBragiRuntime())

    accepted = await consumer.handle(bus=bus, envelope=_request_envelope())

    assert accepted is False
    dlq = [
        event async for event in bus.subscribe(f"{POST_TURN_REVIEW_REQUEST_TOPIC}.dlq", "assert")
    ]
    assert [event.payload["reason"] for event in dlq] == ["post_turn_review_publish_failed"]


class _FailingBragi:
    async def publish_post_turn_review(self, review: object) -> bool:
        raise ConnectionError("bus unavailable")


class _FailingBragiRuntime:
    agents: dict[str, Any] = {"Bragi": _FailingBragi()}
