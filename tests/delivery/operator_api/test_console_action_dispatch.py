from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fdai.delivery.operator_api.console_action_dispatch import (
    ConsoleActionDispatchConflictError,
    ConsoleActionDispatcher,
    ConsoleActionDispatcherConfig,
    ConsoleActionDispatchRecovery,
    ConsoleActionDispatchState,
    ConsoleActionDispatchStore,
    console_action_intent_digest,
)
from fdai.delivery.operator_api.console_incident_ticket import ConsoleIncidentTicketCoordinator
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


def _ticket_payload(incident_id: str) -> dict[str, object]:
    correlation_id = f"incident-ticket:{incident_id}"
    return {
        "idempotency_key": correlation_id,
        "correlation_id": correlation_id,
        "initiator_principal": "user-1",
        "operator_initiated": True,
        "action_type": "tool.open-incident-ticket",
        "resource_id": f"incident:{incident_id}",
        "event_type": "operator_request",
        "params": {"incident_id": incident_id},
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


async def test_malformed_durable_row_does_not_poison_pending_recovery() -> None:
    dispatcher, state_store, bus, clock = _dispatcher()
    payload = _payload()
    pending, _created = await dispatcher.store.enqueue(
        idempotency_key="user-1::recoverable",
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
    await state_store.write_state(
        "console_action_dispatch:poison",
        {"schema_version": "unsupported", "dispatch_id": "poison"},
    )

    assert await dispatcher.drain_due() == 1
    recovered = await dispatcher.store.get(pending.dispatch_id)
    assert recovered is not None
    assert recovered.state is ConsoleActionDispatchState.PUBLISHED
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
    with pytest.raises(ConsoleActionDispatchConflictError) as conflict:
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

    assert conflict.value.dispatch_id
    assert conflict.value.correlation_id == "correlation-1"
    assert conflict.value.accepted_at == _clock()
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


async def test_stale_blocked_ticket_does_not_starve_later_open_incident() -> None:
    dispatcher, state_store, bus, clock = _dispatcher()
    stale_payload = _ticket_payload("incident-stale")
    valid_payload = _ticket_payload("incident-valid")
    for payload in (stale_payload, valid_payload):
        resource_id = str(payload["resource_id"])
        await dispatcher.prepare_blocked(
            idempotency_key=str(payload["idempotency_key"]),
            intent_digest=console_action_intent_digest(
                topic=_TOPIC,
                partition_key=resource_id,
                payload=payload,
            ),
            topic=_TOPIC,
            partition_key=resource_id,
            payload=payload,
            correlation_id=str(payload["correlation_id"]),
            actor_oid="user-1",
        )
        clock.advance(1)
    await state_store.append_incident_transition(
        {
            "kind": "incident.open",
            "idempotency_key": "incident-valid::open",
            "correlation_id": "incident-valid",
            "incident_id": "incident-valid",
            "severity": "sev2",
            "state": "open",
            "actor_oid": "user-1",
            "opened_at": clock().isoformat(),
            "assignee_oid": None,
            "correlation_keys": ["target:valid"],
            "member_event_ids": [],
        }
    )
    coordinator = ConsoleIncidentTicketCoordinator(
        dispatcher=dispatcher,
        state_store=state_store,
        event_topic=_TOPIC,
        batch_size=1,
    )

    assert await coordinator.reconcile() == 1
    assert await _records(bus) == [valid_payload]


async def test_orphaned_blocked_ticket_is_auditably_abandoned_after_retention() -> None:
    dispatcher, state_store, bus, clock = _dispatcher()
    payload = _ticket_payload("incident-orphaned")
    resource_id = str(payload["resource_id"])
    record = await dispatcher.prepare_blocked(
        idempotency_key=str(payload["idempotency_key"]),
        intent_digest=console_action_intent_digest(
            topic=_TOPIC,
            partition_key=resource_id,
            payload=payload,
        ),
        topic=_TOPIC,
        partition_key=resource_id,
        payload=payload,
        correlation_id=str(payload["correlation_id"]),
        actor_oid="user-1",
    )
    coordinator = ConsoleIncidentTicketCoordinator(
        dispatcher=dispatcher,
        state_store=state_store,
        event_topic=_TOPIC,
        batch_size=1,
        blocked_retention_seconds=10,
    )

    clock.advance(11)
    assert await coordinator.reconcile() == 0

    abandoned = await dispatcher.store.get(record.dispatch_id)
    assert abandoned is not None
    assert abandoned.state is ConsoleActionDispatchState.ABANDONED
    assert abandoned.last_error == "incident_not_opened_before_retention_expiry"
    assert await _records(bus) == []
    assert state_store.audit_entries[-1]["entry"]["kind"] == ("console.action.dispatch.abandoned")


async def test_periodic_recovery_continues_after_one_cycle_fails() -> None:
    dispatcher, _state_store, _bus, _clock = _dispatcher()
    completed = asyncio.Event()
    attempts = 0

    async def reconcile() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("transient reconciliation failure")
        if attempts == 3:
            completed.set()

    recovery = ConsoleActionDispatchRecovery(
        dispatcher=dispatcher,
        interval_seconds=0.001,
        reconcile=reconcile,
    )

    await recovery.start()
    await asyncio.wait_for(completed.wait(), timeout=1)
    await recovery.stop()

    assert attempts >= 3


async def test_recovery_stop_cancels_in_flight_cycle() -> None:
    dispatcher, _state_store, _bus, _clock = _dispatcher()
    cycle_started = asyncio.Event()
    cycle_cancelled = asyncio.Event()
    calls = 0

    async def reconcile() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return
        cycle_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cycle_cancelled.set()

    recovery = ConsoleActionDispatchRecovery(
        dispatcher=dispatcher,
        interval_seconds=0.001,
        reconcile=reconcile,
    )

    await recovery.start()
    await asyncio.wait_for(cycle_started.wait(), timeout=1)
    await asyncio.wait_for(recovery.stop(), timeout=1)

    assert cycle_cancelled.is_set()
