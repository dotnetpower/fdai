"""The Console inbox channel stores one bounded no-authority record per A2 message."""

from __future__ import annotations

import pytest
from fdai.core.notifications import (
    InMemoryNotificationDeliveryStore,
    NotificationRouter,
    RouteOutcome,
    load_matrix_from_mapping,
)
from fdai.core.notifications.router import ChannelRegistry
from fdai.delivery.notifications.console_inbox import (
    CONSOLE_INBOX_CHANNEL_ID,
    CONSOLE_INBOX_PREFIX,
    StateStoreConsoleInboxChannel,
)
from fdai.runtime.notification_registry import with_console_inbox
from fdai.shared.providers.notifications import (
    ChannelDeliveryError,
    ChannelKind,
    NotificationMessage,
    Severity,
    TrustTier,
)
from fdai.shared.providers.testing.notifications import FakeHilEscalationSink
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _message(**overrides: object) -> NotificationMessage:
    values: dict[str, object] = {
        "category": "operational_alert",
        "trust_tier": TrustTier.A2_OPERATIONAL_ALERT,
        "correlation_id": "incident-1",
        "audit_id": "audit-1",
        "title": "Incident opened",
        "body_markdown": "An Incident was opened for api-example.",
        "severity": Severity.ERROR,
    }
    values.update(overrides)
    return NotificationMessage(**values)  # type: ignore[arg-type]


async def test_send_writes_one_content_minimal_record_and_is_idempotent() -> None:
    store = InMemoryStateStore()
    channel = StateStoreConsoleInboxChannel(state_store=store)

    first = await channel.send(_message())
    second = await channel.send(_message())

    rows = await store.read_states(CONSOLE_INBOX_PREFIX, limit=10)
    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Incident opened"
    assert record["severity"] == "error"
    assert record["trust_tier"] == "a2_operational_alert"
    assert record["execution_authority"] is False
    assert set(record) == {
        "schema_version",
        "inbox_id",
        "category",
        "trust_tier",
        "severity",
        "title",
        "body",
        "correlation_id",
        "audit_id",
        "recorded_at",
        "execution_authority",
    }
    assert first.delivered and second.delivered
    assert first.channel_kind is ChannelKind.CONSOLE
    assert first.provider_message_id == second.provider_message_id == record["inbox_id"]


async def test_secret_like_content_is_rejected_before_any_write() -> None:
    store = InMemoryStateStore()
    channel = StateStoreConsoleInboxChannel(state_store=store)

    with pytest.raises(ChannelDeliveryError):
        await channel.send(_message(body_markdown="password=correct-horse-battery"))

    assert await store.read_states(CONSOLE_INBOX_PREFIX, limit=10) == ()


async def test_retention_keeps_only_the_newest_records() -> None:
    store = InMemoryStateStore()
    channel = StateStoreConsoleInboxChannel(state_store=store, retained=3)

    for index in range(6):
        await channel.send(_message(audit_id=f"audit-{index}", title=f"Alert {index}"))

    rows = await store.read_states(CONSOLE_INBOX_PREFIX, limit=10)
    assert [row["title"] for row in rows] == ["Alert 5", "Alert 4", "Alert 3"]


def test_binding_is_opt_out_and_never_replaces_an_explicit_channel() -> None:
    store = InMemoryStateStore()
    bound = with_console_inbox(ChannelRegistry(), store, {})
    off = with_console_inbox(ChannelRegistry(), store, {"FDAI_CONSOLE_INBOX": "0"})

    assert CONSOLE_INBOX_CHANNEL_ID in bound.channels
    assert bound.binding(CONSOLE_INBOX_CHANNEL_ID).trust_tiers == frozenset(
        {TrustTier.A2_OPERATIONAL_ALERT}
    )
    assert CONSOLE_INBOX_CHANNEL_ID not in off.channels
    assert with_console_inbox(bound, store, {}) is bound


async def test_a2_alert_is_delivered_to_the_inbox_instead_of_escalating() -> None:
    audit = InMemoryStateStore()
    sink = FakeHilEscalationSink()
    registry = with_console_inbox(ChannelRegistry(), audit, {})
    matrix = load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "operational_alert",
                "routes": {
                    "operational_alert": {
                        "trust_tier": TrustTier.A2_OPERATIONAL_ALERT.value,
                        "delivery_mode": "fanout",
                        "channels": ["teams-ops-prd", CONSOLE_INBOX_CHANNEL_ID],
                    }
                },
            }
        }
    )
    router = NotificationRouter(
        matrix=matrix,
        registry=registry,
        audit_store=audit,
        hil_sink=sink,
        delivery_store=InMemoryNotificationDeliveryStore(),
        retry_backoff_seconds=0,
    )

    result = await router.dispatch(_message())

    assert result.outcome is RouteOutcome.DELIVERED_ALL
    assert result.target_channel_ids == (CONSOLE_INBOX_CHANNEL_ID,)
    assert result.excluded_channels == {"teams-ops-prd": "configuration_invalid"}
    assert tuple(sink.entries) == ()
    assert len(await audit.read_states(CONSOLE_INBOX_PREFIX, limit=10)) == 1
