"""Authenticated Teams Workflows publication receipt verification."""

from __future__ import annotations

import json
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
    TeamsWebhookChannel,
    TeamsWebhookConfig,
    TeamsWorkflowReceiptConfig,
    TeamsWorkflowReceiptHandler,
    compute_receipt_signature,
)
from fdai.shared.providers.notifications import NotificationMessage, TrustTier
from fdai.shared.providers.testing.notifications import FakeHilEscalationSink
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
SECRET = "test-receipt-secret"


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


def _signed_body(result: str = "published") -> tuple[bytes, dict[str, str]]:
    body = json.dumps(
        {
            "audit_id": "audit-1",
            "channel_id": "teams-ops",
            "publication_result": result,
            "provider_message_id": "workflow-run-1",
        },
        separators=(",", ":"),
    ).encode()
    timestamp = NOW.isoformat()
    signature = compute_receipt_signature(
        secret=SECRET,
        timestamp=timestamp,
        body=body,
    )
    return body, {
        "X-FDAI-Timestamp": timestamp,
        "X-FDAI-Signature": f"sha256={signature}",
    }


async def test_authenticated_publication_receipt_confirms_delivery_and_audits() -> None:
    store = await _accepted_store()
    audit = InMemoryStateStore()
    handler = TeamsWorkflowReceiptHandler(
        config=TeamsWorkflowReceiptConfig(secret=SECRET),
        delivery_store=store,
        audit_store=audit,
        clock=lambda: NOW,
    )
    body, headers = _signed_body()

    record = await handler.handle(headers=headers, body=body)

    assert record.state is ChannelDeliveryState.DELIVERED
    entries = list(audit.audit_entries)
    assert len(entries) == 2
    assert [item["entry"]["phase"] for item in entries] == ["prepared", "completed"]
    assert all(item["entry"]["action_kind"] == "notification.delivery.observed" for item in entries)
    assert all("body" not in item["entry"] for item in entries)


async def test_failed_publication_becomes_retryable() -> None:
    store = await _accepted_store()
    handler = TeamsWorkflowReceiptHandler(
        config=TeamsWorkflowReceiptConfig(secret=SECRET),
        delivery_store=store,
        audit_store=InMemoryStateStore(),
        clock=lambda: NOW,
    )
    body, headers = _signed_body("failed")

    record = await handler.handle(headers=headers, body=body)

    assert record.state is ChannelDeliveryState.RETRYABLE_FAILED


async def test_invalid_signature_and_message_field_are_rejected() -> None:
    store = await _accepted_store()
    handler = TeamsWorkflowReceiptHandler(
        config=TeamsWorkflowReceiptConfig(secret=SECRET),
        delivery_store=store,
        audit_store=InMemoryStateStore(),
        clock=lambda: NOW,
    )
    body, headers = _signed_body()
    headers["X-FDAI-Signature"] = "sha256=bad"
    with pytest.raises(PermissionError, match="mismatch"):
        await handler.handle(headers=headers, body=body)

    forbidden = json.dumps(
        {
            "audit_id": "audit-1",
            "channel_id": "teams-ops",
            "publication_result": "published",
            "message": "must not be returned",
        }
    ).encode()
    timestamp = NOW.isoformat()
    signature = compute_receipt_signature(
        secret=SECRET,
        timestamp=timestamp,
        body=forbidden,
    )
    with pytest.raises(ValueError, match="unsupported fields"):
        await handler.handle(
            headers={
                "X-FDAI-Timestamp": timestamp,
                "X-FDAI-Signature": f"sha256={signature}",
            },
            body=forbidden,
        )


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

        handler = TeamsWorkflowReceiptHandler(
            config=TeamsWorkflowReceiptConfig(secret=SECRET),
            delivery_store=delivery_store,
            audit_store=audit,
            clock=lambda: NOW,
        )
        body, headers = _signed_body()
        await handler.handle(headers=headers, body=body)
        delivered = await router.dispatch(message)

    assert delivered.outcome is RouteOutcome.DELIVERED_ALL
    assert delivered.terminal is True
    assert requests == 1
