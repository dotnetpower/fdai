from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fdai.delivery.read_api.console_action_dispatch import (
    ConsoleActionDispatchConflictError,
    ConsoleActionDispatcher,
    ConsoleActionDispatcherConfig,
    ConsoleActionDispatchState,
    ConsoleActionDispatchStore,
    console_action_intent_digest,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_TOPIC = "aw.events"


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class _FailOnceBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.failures = 1

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("broker unavailable")
        return await super().publish(topic, key, payload)


class _FailPublishedReceiptOnceStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_published = True

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if self.fail_published and value.get("state") == "published":
            self.fail_published = False
            return False
        return await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )


async def _records(bus: InMemoryEventBus) -> list[dict[str, Any]]:
    return [event.payload async for event in bus.subscribe(_TOPIC, "test")]


def _payload(*, action_type: str = "ops.restart-service") -> dict[str, object]:
    return {
        "idempotency_key": "user-1::request-1",
        "correlation_id": "correlation-1",
        "initiator_principal": "user-1",
        "operator_initiated": True,
        "action_type": action_type,
        "resource_id": "service-1",
        "event_type": "operator_request",
        "params": {"question": "restart service-1"},
    }


def _dispatcher(
    *,
    bus: InMemoryEventBus | None = None,
    clock: _Clock | None = None,
    state_store: InMemoryStateStore | None = None,
) -> tuple[ConsoleActionDispatcher, InMemoryStateStore, InMemoryEventBus, _Clock]:
    resolved_bus = bus or InMemoryEventBus()
    resolved_clock = clock or _Clock()
    resolved_state_store = state_store or InMemoryStateStore()
    dispatcher = ConsoleActionDispatcher(
        store=ConsoleActionDispatchStore(resolved_state_store),
        event_bus=resolved_bus,
        config=ConsoleActionDispatcherConfig(
            worker_id="worker-1",
            lease_seconds=10,
            publish_timeout_seconds=2,
            retry_delay_seconds=5,
            batch_size=10,
        ),
        clock=resolved_clock,
    )
    return dispatcher, resolved_state_store, resolved_bus, resolved_clock


async def test_submit_persists_before_publish_and_records_receipt() -> None:
    dispatcher, state_store, bus, _clock = _dispatcher()
    payload = _payload()

    record = await dispatcher.submit(
        idempotency_key=str(payload["idempotency_key"]),
        intent_digest=console_action_intent_digest(
            topic=_TOPIC,
            partition_key="service-1",
            payload=payload,
        ),
        topic=_TOPIC,
        partition_key="service-1",
        payload=payload,
        correlation_id="correlation-1",
        actor_oid="user-1",
    )

    assert record.state is ConsoleActionDispatchState.PUBLISHED
    assert record.attempt_count == 1
    assert await _records(bus) == [payload]
    kinds = [entry["entry"]["kind"] for entry in state_store.audit_entries]
    assert kinds == [
        "console.action.dispatch.accepted",
        "console.action.dispatch.claimed",
        "console.action.dispatch.published",
    ]


async def test_retry_after_publish_failure_redrives_durable_payload() -> None:
    bus = _FailOnceBus()
    clock = _Clock()
    dispatcher, _state_store, _bus, _clock = _dispatcher(bus=bus, clock=clock)
    payload = _payload()

    pending = await dispatcher.submit(
        idempotency_key="user-1::request-1",
        intent_digest=console_action_intent_digest(
            topic=_TOPIC,
            partition_key="service-1",
            payload=payload,
        ),
        topic=_TOPIC,
        partition_key="service-1",
        payload=payload,
        correlation_id="correlation-1",
        actor_oid="user-1",
    )

    assert pending.state is ConsoleActionDispatchState.PENDING
    assert pending.last_error == "publish:RuntimeError"
    assert await _records(bus) == []

    clock.advance(5)
    assert await dispatcher.drain_due() == 1
    published = await dispatcher.store.get(pending.dispatch_id)
    assert published is not None
    assert published.state is ConsoleActionDispatchState.PUBLISHED
    assert published.attempt_count == 2
    assert await _records(bus) == [payload]


async def test_replay_returns_published_record_without_republishing() -> None:
    dispatcher, _state_store, bus, _clock = _dispatcher()
    payload = _payload()
    digest = console_action_intent_digest(
        topic=_TOPIC,
        partition_key="service-1",
        payload=payload,
    )

    first = await dispatcher.submit(
        idempotency_key="user-1::request-1",
        intent_digest=digest,
        topic=_TOPIC,
        partition_key="service-1",
        payload=payload,
        correlation_id="correlation-1",
        actor_oid="user-1",
    )
    second = await dispatcher.submit(
        idempotency_key="user-1::request-1",
        intent_digest=digest,
        topic=_TOPIC,
        partition_key="service-1",
        payload=payload,
        correlation_id="another-correlation",
        actor_oid="user-1",
    )

    assert second == first
    assert len(await _records(bus)) == 1


async def test_idempotency_key_conflict_never_publishes_second_intent() -> None:
    dispatcher, _state_store, bus, _clock = _dispatcher()
    first_payload = _payload()
    second_payload = _payload(action_type="ops.scale-out")

    await dispatcher.submit(
        idempotency_key="user-1::request-1",
        intent_digest=console_action_intent_digest(
            topic=_TOPIC,
            partition_key="service-1",
            payload=first_payload,
        ),
        topic=_TOPIC,
        partition_key="service-1",
        payload=first_payload,
        correlation_id="correlation-1",
        actor_oid="user-1",
    )
    with pytest.raises(ConsoleActionDispatchConflictError):
        await dispatcher.submit(
            idempotency_key="user-1::request-1",
            intent_digest=console_action_intent_digest(
                topic=_TOPIC,
                partition_key="service-1",
                payload=second_payload,
            ),
            topic=_TOPIC,
            partition_key="service-1",
            payload=second_payload,
            correlation_id="correlation-2",
            actor_oid="user-1",
        )

    assert await _records(bus) == [first_payload]


async def test_expired_lease_is_reclaimed_after_process_loss() -> None:
    dispatcher, _state_store, bus, clock = _dispatcher()
    payload = _payload()
    record, _created = await dispatcher.store.enqueue(
        idempotency_key="user-1::request-1",
        intent_digest=console_action_intent_digest(
            topic=_TOPIC,
            partition_key="service-1",
            payload=payload,
        ),
        topic=_TOPIC,
        partition_key="service-1",
        payload=payload,
        correlation_id="correlation-1",
        actor_oid="user-1",
        now=clock(),
    )
    claimed = await dispatcher.store.claim(
        record.dispatch_id,
        now=clock(),
        lease_owner="dead-worker",
        lease_seconds=10,
    )
    assert claimed is not None

    clock.advance(11)
    assert await dispatcher.drain_due() == 1
    recovered = await dispatcher.store.get(record.dispatch_id)
    assert recovered is not None
    assert recovered.state is ConsoleActionDispatchState.PUBLISHED
    assert recovered.attempt_count == 2
    assert await _records(bus) == [payload]


async def test_publish_receipt_cas_failure_returns_durable_record_and_recovers() -> None:
    state_store = _FailPublishedReceiptOnceStore()
    dispatcher, _state_store, bus, clock = _dispatcher(state_store=state_store)
    payload = _payload()

    accepted = await dispatcher.submit(
        idempotency_key="user-1::request-1",
        intent_digest=console_action_intent_digest(
            topic=_TOPIC,
            partition_key="service-1",
            payload=payload,
        ),
        topic=_TOPIC,
        partition_key="service-1",
        payload=payload,
        correlation_id="correlation-1",
        actor_oid="user-1",
    )

    assert accepted.state is ConsoleActionDispatchState.PUBLISHING
    assert len(await _records(bus)) == 1

    clock.advance(11)
    assert await dispatcher.drain_due() == 1
    recovered = await dispatcher.store.get(accepted.dispatch_id)
    assert recovered is not None
    assert recovered.state is ConsoleActionDispatchState.PUBLISHED
    assert recovered.attempt_count == 2
    assert await _records(bus) == [payload]
