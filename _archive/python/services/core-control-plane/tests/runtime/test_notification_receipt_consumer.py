"""Core consumption of authenticated notification publication observations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fdai.core.notifications import (
    ChannelDeliveryState,
    InMemoryNotificationDeliveryStore,
)
from fdai.delivery.notifications import NotificationDeliveryReceiptApplier
from fdai.runtime.bootstrap_tasks import _notification_receipt_topic
from fdai.runtime.consumers import _consume_notification_receipts
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.notification_receipt import (
    NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
    NotificationDeliveryReceipt,
    encode_notification_delivery_receipt,
)

NOW = datetime(2026, 9, 4, 7, 0, tzinfo=UTC)


def test_notification_receipt_topic_is_canonical() -> None:
    assert _notification_receipt_topic({}) == NOTIFICATION_DELIVERY_RECEIPT_TOPIC
    with pytest.raises(RuntimeError, match="canonical logical topic"):
        _notification_receipt_topic(
            {"FDAI_NOTIFICATION_RECEIPT_TOPIC": "fdai.notifications.delivery-receipts-prod"}
        )


async def _accepted_store() -> InMemoryNotificationDeliveryStore:
    store = InMemoryNotificationDeliveryStore()
    await store.create_plan(
        audit_id="audit-1",
        target_channel_ids=("teams-ops",),
        excluded_channels={},
        now=NOW,
    )
    claim = await store.claim(
        audit_id="audit-1",
        channel_id="teams-ops",
        now=NOW,
        lease_seconds=60,
        max_attempts=3,
    )
    assert claim.record.token is not None
    await store.record_result(
        audit_id="audit-1",
        channel_id="teams-ops",
        token=claim.record.token,
        state=ChannelDeliveryState.ACCEPTED,
        at=NOW,
        confirmation_timeout_seconds=300,
    )
    return store


def _envelope(result: str = "published") -> dict[str, object]:
    return encode_notification_delivery_receipt(
        NotificationDeliveryReceipt(
            audit_id="audit-1",
            channel_id="teams-ops",
            publication_result=result,
            observed_at=NOW,
            provider_message_id="run-1",
        )
    )


async def _drain(bus: InMemoryEventBus, applier: NotificationDeliveryReceiptApplier) -> None:
    stop = asyncio.Event()
    await _consume_notification_receipts(
        bus=bus,
        topic=NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
        applier=applier,
        stop=stop,
    )


async def test_consumer_promotes_accepted_delivery_to_delivered() -> None:
    store = await _accepted_store()
    audit = InMemoryStateStore()
    bus = InMemoryEventBus()
    await bus.publish(NOTIFICATION_DELIVERY_RECEIPT_TOPIC, "audit-1", _envelope())

    await _drain(
        bus,
        NotificationDeliveryReceiptApplier(
            delivery_store=store,
            audit_store=audit,
            clock=lambda: NOW,
        ),
    )

    plan = await store.snapshot(audit_id="audit-1", now=NOW)
    assert plan.deliveries[0].state is ChannelDeliveryState.DELIVERED
    assert [item["entry"]["phase"] for item in audit.audit_entries] == ["prepared", "completed"]


async def test_consumer_dead_letters_a_malformed_envelope_without_touching_state() -> None:
    store = await _accepted_store()
    bus = InMemoryEventBus()
    await bus.publish(
        NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
        "audit-1",
        {"schema_version": "1.0.0", "audit_id": "audit-1"},
    )

    await _drain(
        bus,
        NotificationDeliveryReceiptApplier(
            delivery_store=store,
            audit_store=InMemoryStateStore(),
            clock=lambda: NOW,
        ),
    )

    plan = await store.snapshot(audit_id="audit-1", now=NOW)
    assert plan.deliveries[0].state is ChannelDeliveryState.ACCEPTED


async def test_consumer_dead_letters_an_observation_for_a_missing_plan() -> None:
    store = InMemoryNotificationDeliveryStore()
    audit = InMemoryStateStore()
    bus = InMemoryEventBus()
    await bus.publish(NOTIFICATION_DELIVERY_RECEIPT_TOPIC, "audit-1", _envelope())

    await _drain(
        bus,
        NotificationDeliveryReceiptApplier(
            delivery_store=store,
            audit_store=audit,
            clock=lambda: NOW,
        ),
    )

    entries = [item["entry"] for item in audit.audit_entries]
    assert [item["phase"] for item in entries] == ["prepared", "completed"]
    assert entries[-1]["delivery_state"] == "unchanged"
    assert entries[-1]["rejection_reason"] == "delivery_is_not_accepted"


async def test_consumer_returns_failed_publication_to_retryable_state() -> None:
    store = await _accepted_store()
    bus = InMemoryEventBus()
    await bus.publish(NOTIFICATION_DELIVERY_RECEIPT_TOPIC, "audit-1", _envelope("failed"))

    await _drain(
        bus,
        NotificationDeliveryReceiptApplier(
            delivery_store=store,
            audit_store=InMemoryStateStore(),
            clock=lambda: NOW,
        ),
    )

    plan = await store.snapshot(audit_id="audit-1", now=NOW)
    assert plan.deliveries[0].state is ChannelDeliveryState.RETRYABLE_FAILED
