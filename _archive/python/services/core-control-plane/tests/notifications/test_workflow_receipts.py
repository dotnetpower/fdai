"""Applying authenticated notification publication observations."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fdai.core.notifications import (
    ChannelDeliveryState,
    ChannelRegistry,
    InMemoryNotificationDeliveryStore,
    NotificationRouter,
    RouteOutcome,
    load_matrix_from_mapping,
)
from fdai.delivery.notifications import (
    NotificationDeliveryReceiptApplier,
    NotificationReceiptRejectedError,
    TeamsWebhookChannel,
    TeamsWebhookConfig,
)
from fdai.shared.providers.notifications import NotificationMessage, TrustTier
from fdai.shared.providers.testing.notifications import FakeHilEscalationSink
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.notification_receipt import NotificationDeliveryReceipt

NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


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


def _receipt(result: str = "published") -> NotificationDeliveryReceipt:
    return NotificationDeliveryReceipt(
        audit_id="audit-1",
        channel_id="teams-ops",
        publication_result=result,
        observed_at=NOW,
        provider_message_id="workflow-run-1",
    )


async def test_published_observation_confirms_delivery_and_audits_both_phases() -> None:
    store = await _accepted_store()
    audit = InMemoryStateStore()
    applier = NotificationDeliveryReceiptApplier(
        delivery_store=store,
        audit_store=audit,
        clock=lambda: NOW,
    )

    record = await applier.apply(_receipt())

    assert record.state is ChannelDeliveryState.DELIVERED
    entries = list(audit.audit_entries)
    assert [item["entry"]["phase"] for item in entries] == ["prepared", "completed"]
    assert all(item["entry"]["action_kind"] == "notification.delivery.observed" for item in entries)
    assert entries[0]["entry"]["intended_delivery_state"] == "delivered"
    assert entries[1]["entry"]["delivery_state"] == "delivered"
    assert all("body" not in item["entry"] for item in entries)
    assert all("webhook_url" not in item["entry"] for item in entries)


async def test_failed_publication_becomes_retryable() -> None:
    store = await _accepted_store()
    applier = NotificationDeliveryReceiptApplier(
        delivery_store=store,
        audit_store=InMemoryStateStore(),
        clock=lambda: NOW,
    )

    record = await applier.apply(_receipt("failed"))

    assert record.state is ChannelDeliveryState.RETRYABLE_FAILED


async def test_repeated_identical_observation_is_idempotent() -> None:
    store = await _accepted_store()
    applier = NotificationDeliveryReceiptApplier(
        delivery_store=store,
        audit_store=InMemoryStateStore(),
        clock=lambda: NOW,
    )

    first = await applier.apply(_receipt())
    second = await applier.apply(_receipt())

    assert first.state is ChannelDeliveryState.DELIVERED
    assert second.state is ChannelDeliveryState.DELIVERED


async def test_observation_for_a_non_accepted_delivery_is_rejected_and_audited() -> None:
    store = InMemoryNotificationDeliveryStore()
    await store.create_plan(
        audit_id="audit-1",
        target_channel_ids=("teams-ops",),
        excluded_channels={},
        now=NOW,
    )
    audit = InMemoryStateStore()
    applier = NotificationDeliveryReceiptApplier(
        delivery_store=store,
        audit_store=audit,
        clock=lambda: NOW,
    )

    with pytest.raises(NotificationReceiptRejectedError):
        await applier.apply(_receipt())

    completed = list(audit.audit_entries)[-1]["entry"]
    assert completed["phase"] == "completed"
    assert completed["delivery_state"] == "unchanged"
    assert completed["rejection_reason"] == "delivery_is_not_accepted"


async def test_observation_for_a_missing_plan_is_rejected_and_audited() -> None:
    audit = InMemoryStateStore()
    applier = NotificationDeliveryReceiptApplier(
        delivery_store=InMemoryNotificationDeliveryStore(),
        audit_store=audit,
        clock=lambda: NOW,
    )

    with pytest.raises(NotificationReceiptRejectedError):
        await applier.apply(_receipt())

    entries = [item["entry"] for item in audit.audit_entries]
    assert [item["phase"] for item in entries] == ["prepared", "completed"]
    assert entries[-1]["delivery_state"] == "unchanged"
    assert entries[-1]["rejection_reason"] == "delivery_is_not_accepted"


async def test_workflow_acceptance_converges_without_duplicate_send() -> None:
    requests = 0

    def transport(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(202, headers={"x-ms-workflow-run-id": "workflow-run-1"})

    delivery_store = InMemoryNotificationDeliveryStore()
    audit = InMemoryStateStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        channel = TeamsWebhookChannel(
            config=TeamsWebhookConfig(
                channel_id="teams-ops",
                webhook_url="https://flow.example.com/trigger",
                trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            ),
            http_client=client,
        )
        router = NotificationRouter(
            matrix=load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "operational_alert",
                        "routes": {
                            "operational_alert": {
                                "trust_tier": "a2_operational_alert",
                                "delivery_mode": "fanout",
                                "channels": ["teams-ops"],
                            }
                        },
                    }
                }
            ),
            registry=ChannelRegistry(channels={"teams-ops": channel}),
            audit_store=audit,
            hil_sink=FakeHilEscalationSink(),
            delivery_store=delivery_store,
            retry_backoff_seconds=0,
        )
        message = NotificationMessage(
            category="operational_alert",
            trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
            correlation_id="cid-1",
            audit_id="audit-1",
            title="Alert",
            body_markdown="Body",
        )

        accepted = await router.dispatch(message)
        assert accepted.outcome is RouteOutcome.FAILED_ALL
        assert accepted.terminal is False

        applier = NotificationDeliveryReceiptApplier(
            delivery_store=delivery_store,
            audit_store=audit,
            clock=lambda: NOW,
        )
        await applier.apply(_receipt())
        delivered = await router.dispatch(message)

    assert delivered.outcome is RouteOutcome.DELIVERED_ALL
    assert delivered.terminal is True
    assert requests == 1
