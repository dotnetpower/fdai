"""Focused tests for durable Rule generation EventBus publication."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import pytest
from fdai.core.rule_semantic_generation import (
    RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
    RuleGenerationOutboxPublisher,
    RuleGenerationPublishRetryableError,
    RuleGenerationReceiptMismatchError,
    StateStoreRuleGenerationOutboxLedger,
)
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationActivationResultEvent,
    RuleGenerationOutboxDeliveryState,
    RuleGenerationOutboxRecord,
)
from fdai.shared.providers.event_bus import EventEnvelope, PublishReceipt
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.rule_semantic_generation.test_ledger import NOW, _request_id, _result

_WATCHDOG_SECONDS = 0.5


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class _ControlledEventBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.block = False
        self.fail = False
        self.wrong_receipt = False
        self.attempts = 0
        self.entered = asyncio.Event()

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        if topic == RULE_GENERATION_ACTIVATION_RESULT_TOPIC:
            self.attempts += 1
            if self.block:
                self.entered.set()
                await asyncio.Event().wait()
            if self.fail:
                raise RuntimeError("synthetic broker failure")
            if self.wrong_receipt:
                return PublishReceipt(topic="wrong.topic", partition=0, offset=0)
        return await super().publish(topic, key, payload)


class _FailingCompleteLedger(StateStoreRuleGenerationOutboxLedger):
    def __init__(self, *, store: InMemoryStateStore) -> None:
        super().__init__(store=store)
        self.fail_complete = True

    async def complete_outbox(
        self,
        generation_request_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        published_at: datetime,
    ) -> None:
        if self.fail_complete:
            raise RuntimeError("synthetic acknowledgement persistence failure")
        await super().complete_outbox(
            generation_request_id,
            idempotency_key,
            claimant_id=claimant_id,
            published_at=published_at,
        )


def _publisher(
    *,
    ledger: StateStoreRuleGenerationOutboxLedger,
    event_bus: InMemoryEventBus,
    clock: _FakeClock,
    claimant_id: str = "rule-generation-publisher",
    publish_timeout_seconds: float = 0.1,
) -> RuleGenerationOutboxPublisher:
    return RuleGenerationOutboxPublisher(
        ledger=ledger,
        event_bus=event_bus,
        claimant_id=claimant_id,
        clock=clock,
        publish_timeout_seconds=publish_timeout_seconds,
    )


async def _delivery(
    store: InMemoryStateStore,
    result: RuleGenerationActivationResultEvent,
) -> RuleGenerationOutboxRecord:
    aggregate = await store.read_state(f"rule-semantic-generation:activation:{_request_id(result)}")
    assert aggregate is not None
    return RuleGenerationOutboxRecord.model_validate(aggregate["outbox"][result.idempotency_key])


async def _records(event_bus: InMemoryEventBus) -> tuple[EventEnvelope, ...]:
    return tuple(
        [
            envelope
            async for envelope in event_bus.subscribe(
                RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
                "publication-assertions",
            )
        ]
    )


async def test_publish_acknowledges_exact_receipt_and_suppresses_duplicate() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleGenerationOutboxLedger(store=store)
    result = await ledger.commit_result(_result())
    event_bus = InMemoryEventBus()
    publisher = _publisher(ledger=ledger, event_bus=event_bus, clock=_FakeClock(NOW))

    assert await publisher.publish_pending_once() == result
    assert await publisher.publish_pending_once() is None
    records = await _records(event_bus)
    assert len(records) == 1
    assert records[0].key == _request_id(result)
    assert RuleGenerationActivationResultEvent.model_validate(records[0].payload) == result
    delivery = await _delivery(store, result)
    assert delivery.state is RuleGenerationOutboxDeliveryState.PUBLISHED
    assert delivery.published_at == NOW


async def test_publish_failure_releases_for_restart_safe_retry() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleGenerationOutboxLedger(store=store)
    result = await ledger.commit_result(_result())
    event_bus = _ControlledEventBus()
    event_bus.fail = True
    clock = _FakeClock(NOW)
    publisher = _publisher(ledger=ledger, event_bus=event_bus, clock=clock)

    with pytest.raises(RuleGenerationPublishRetryableError) as exc_info:
        await publisher.publish_pending_once()
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    delivery = await _delivery(store, result)
    assert delivery.state is RuleGenerationOutboxDeliveryState.PENDING
    assert delivery.attempts == 1
    assert delivery.available_at == NOW + timedelta(seconds=5)
    assert delivery.last_error == "broker_publish_failed"
    assert await publisher.publish_pending_once() is None

    event_bus.fail = False
    clock.advance(timedelta(seconds=5))
    restarted = _publisher(
        ledger=StateStoreRuleGenerationOutboxLedger(store=store),
        event_bus=event_bus,
        clock=clock,
        claimant_id="rule-generation-publisher-restarted",
    )
    assert await restarted.publish_pending_once() == result
    assert event_bus.attempts == 2


async def test_wrong_receipt_topic_is_classified_as_fatal_contract_failure() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleGenerationOutboxLedger(store=store)
    result = await ledger.commit_result(_result())
    event_bus = _ControlledEventBus()
    event_bus.wrong_receipt = True
    publisher = _publisher(ledger=ledger, event_bus=event_bus, clock=_FakeClock(NOW))

    with pytest.raises(RuleGenerationReceiptMismatchError):
        await publisher.publish_pending_once()

    delivery = await _delivery(store, result)
    assert delivery.state is RuleGenerationOutboxDeliveryState.PENDING
    assert delivery.last_error == "broker_receipt_topic_mismatch"


async def test_publish_timeout_releases_without_inline_retry() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleGenerationOutboxLedger(store=store)
    result = await ledger.commit_result(_result())
    event_bus = _ControlledEventBus()
    event_bus.block = True
    publisher = _publisher(
        ledger=ledger,
        event_bus=event_bus,
        clock=_FakeClock(NOW),
        publish_timeout_seconds=0.01,
    )

    with pytest.raises(RuleGenerationPublishRetryableError) as exc_info:
        await asyncio.wait_for(publisher.publish_pending_once(), timeout=_WATCHDOG_SECONDS)
    assert isinstance(exc_info.value.__cause__, TimeoutError)
    delivery = await _delivery(store, result)
    assert delivery.state is RuleGenerationOutboxDeliveryState.PENDING
    assert delivery.last_error == "broker_publish_timeout"
    assert event_bus.attempts == 1


async def test_ack_persistence_failure_republishes_after_lease_expiry() -> None:
    store = InMemoryStateStore()
    ledger = _FailingCompleteLedger(store=store)
    result = await ledger.commit_result(_result())
    event_bus = InMemoryEventBus()
    clock = _FakeClock(NOW)
    publisher = _publisher(ledger=ledger, event_bus=event_bus, clock=clock)

    with pytest.raises(RuntimeError, match="acknowledgement persistence failure"):
        await publisher.publish_pending_once()
    assert (await _delivery(store, result)).state is RuleGenerationOutboxDeliveryState.CLAIMED

    ledger.fail_complete = False
    clock.advance(timedelta(seconds=10))
    assert await publisher.publish_pending_once() == result
    records = await _records(event_bus)
    assert len(records) == 2
    assert {record.key for record in records} == {_request_id(result)}
    assert (await _delivery(store, result)).state is RuleGenerationOutboxDeliveryState.PUBLISHED


async def test_cancelled_publish_reclaims_after_lease_expiry() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleGenerationOutboxLedger(store=store)
    result = await ledger.commit_result(_result())
    event_bus = _ControlledEventBus()
    event_bus.block = True
    clock = _FakeClock(NOW)
    publisher = _publisher(ledger=ledger, event_bus=event_bus, clock=clock)

    task = asyncio.create_task(publisher.publish_pending_once())
    await asyncio.wait_for(event_bus.entered.wait(), timeout=_WATCHDOG_SECONDS)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=_WATCHDOG_SECONDS)
    claimed = await _delivery(store, result)
    assert claimed.state is RuleGenerationOutboxDeliveryState.CLAIMED
    assert claimed.lease_until == NOW + timedelta(seconds=10)

    event_bus.block = False
    restarted = _publisher(
        ledger=StateStoreRuleGenerationOutboxLedger(store=store),
        event_bus=event_bus,
        clock=clock,
        claimant_id="rule-generation-publisher-after-cancel",
    )
    clock.advance(timedelta(seconds=9))
    assert await restarted.publish_pending_once() is None
    clock.advance(timedelta(seconds=1))
    assert await restarted.publish_pending_once() == result


async def test_concurrent_publishers_claim_one_event_and_drain_is_bounded() -> None:
    ledger = StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore())
    result = await ledger.commit_result(_result())
    event_bus = InMemoryEventBus()
    clock = _FakeClock(NOW)
    first = _publisher(ledger=ledger, event_bus=event_bus, clock=clock, claimant_id="first")
    second = _publisher(ledger=ledger, event_bus=event_bus, clock=clock, claimant_id="second")

    outcomes = await asyncio.gather(
        first.publish_pending_once(),
        second.publish_pending_once(),
    )
    assert outcomes.count(result) == 1
    assert outcomes.count(None) == 1
    assert await first.drain_pending(limit=1) == ()
    with pytest.raises(ValueError, match="between 1 and 1000"):
        await first.drain_pending(limit=0)
