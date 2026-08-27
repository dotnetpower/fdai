"""Fan-out routing and durable per-channel state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.notifications import (
    ChannelBinding,
    ChannelDeliveryState,
    ChannelRegistry,
    DeliveryClaimStatus,
    InMemoryNotificationDeliveryStore,
    NotificationRouter,
    RouteOutcome,
    load_matrix_from_mapping,
)
from fdai.shared.providers.notifications import (
    NotificationMessage,
    TrustTier,
)
from fdai.shared.providers.testing.notifications import (
    FakeEmailChannel,
    FakeHilEscalationSink,
    FakeTeamsChannel,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def _message() -> NotificationMessage:
    return NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id="fanout-1",
        audit_id="audit-fanout-1",
        title="Operational alert",
        body_markdown="Body",
    )


def _matrix(*channels: str):
    return load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "operational_alert",
                "routes": {
                    "operational_alert": {
                        "trust_tier": TrustTier.A2_OPERATIONAL_ALERT.value,
                        "delivery_mode": "fanout",
                        "channels": list(channels),
                    }
                },
            }
        }
    )


def _router(
    teams: FakeTeamsChannel,
    email: FakeEmailChannel,
    *,
    delivery_store: InMemoryNotificationDeliveryStore | None = None,
    email_enabled: bool = True,
) -> tuple[NotificationRouter, InMemoryStateStore, FakeHilEscalationSink]:
    audit = InMemoryStateStore()
    sink = FakeHilEscalationSink()
    registry = ChannelRegistry(
        channels={teams.channel_id: teams, email.channel_id: email},
        bindings={
            teams.channel_id: ChannelBinding(
                channel_id=teams.channel_id,
                trust_tiers=teams.trust_tiers,
            ),
            email.channel_id: ChannelBinding(
                channel_id=email.channel_id,
                enabled=email_enabled,
                configured=email_enabled,
                trust_tiers=email.trust_tiers,
            ),
        },
    )
    return (
        NotificationRouter(
            matrix=_matrix(teams.channel_id, email.channel_id),
            registry=registry,
            audit_store=audit,
            hil_sink=sink,
            delivery_store=delivery_store,
            retry_backoff_seconds=0,
        ),
        audit,
        sink,
    )


async def test_fanout_delivers_every_enabled_target_and_audits_once() -> None:
    teams = FakeTeamsChannel(
        channel_id="teams-ops",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    email = FakeEmailChannel(
        channel_id="email-oncall",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    router, audit, sink = _router(teams, email)

    result = await router.dispatch(_message())

    assert result.outcome is RouteOutcome.DELIVERED_ALL
    assert result.target_channel_ids == ("teams-ops", "email-oncall")
    assert {item.state for item in result.deliveries} == {ChannelDeliveryState.DELIVERED}
    assert len(teams.records) == len(email.records) == 1
    assert tuple(sink.entries) == ()
    entries = list(audit.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["outcome"] == "delivered_all"


async def test_fanout_isolates_failure_and_reports_partial_delivery() -> None:
    teams = FakeTeamsChannel(
        channel_id="teams-ops",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    email = FakeEmailChannel(
        channel_id="email-oncall",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    teams.arm_raises(3)
    router, _, sink = _router(teams, email)

    result = await router.dispatch(_message())

    assert result.outcome is RouteOutcome.PARTIALLY_DELIVERED
    states = {item.channel_id: item.state for item in result.deliveries}
    assert states == {
        "teams-ops": ChannelDeliveryState.ABANDONED,
        "email-oncall": ChannelDeliveryState.DELIVERED,
    }
    assert len(email.records) == 1
    assert tuple(sink.entries) == ()


async def test_disabled_binding_is_excluded_before_dispatch() -> None:
    teams = FakeTeamsChannel(
        channel_id="teams-ops",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    email = FakeEmailChannel(
        channel_id="email-oncall",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    router, _, _ = _router(teams, email, email_enabled=False)

    result = await router.dispatch(_message())

    assert result.outcome is RouteOutcome.DELIVERED_ALL
    assert result.target_channel_ids == ("teams-ops",)
    assert result.excluded_channels == {"email-oncall": "disabled"}
    assert len(email.records) == 0


async def test_delivery_store_freezes_targets_and_confirms_only_accepted() -> None:
    store = InMemoryNotificationDeliveryStore()
    first = await store.create_plan(
        audit_id="audit-1",
        target_channel_ids=("teams-ops", "email-oncall"),
        excluded_channels={},
        now=NOW,
    )
    frozen = await store.create_plan(
        audit_id="audit-1",
        target_channel_ids=("email-oncall",),
        excluded_channels={"teams-ops": "disabled"},
        now=NOW,
    )
    assert frozen.target_channel_ids == first.target_channel_ids

    claim = await store.claim(
        audit_id="audit-1",
        channel_id="teams-ops",
        now=NOW,
        lease_seconds=60,
        max_attempts=3,
    )
    assert claim.status is DeliveryClaimStatus.CLAIMED
    assert claim.record.token is not None
    await store.record_result(
        audit_id="audit-1",
        channel_id="teams-ops",
        token=claim.record.token,
        state=ChannelDeliveryState.ACCEPTED,
        at=NOW,
        confirmation_timeout_seconds=30,
    )
    confirmed = await store.confirm_delivered(
        audit_id="audit-1",
        channel_id="teams-ops",
        at=NOW + timedelta(seconds=1),
        provider_message_id="run-1",
    )
    assert confirmed.state is ChannelDeliveryState.DELIVERED
    assert confirmed.provider_message_id == "run-1"


async def test_accepted_delivery_expires_to_ambiguous_without_retry() -> None:
    store = InMemoryNotificationDeliveryStore()
    await store.create_plan(
        audit_id="audit-accepted",
        target_channel_ids=("teams-ops",),
        excluded_channels={},
        now=NOW,
    )
    claim = await store.claim(
        audit_id="audit-accepted",
        channel_id="teams-ops",
        now=NOW,
        lease_seconds=60,
        max_attempts=3,
    )
    assert claim.record.token is not None
    await store.record_result(
        audit_id="audit-accepted",
        channel_id="teams-ops",
        token=claim.record.token,
        state=ChannelDeliveryState.ACCEPTED,
        at=NOW,
        confirmation_timeout_seconds=30,
    )

    snapshot = await store.snapshot(
        audit_id="audit-accepted",
        now=NOW + timedelta(seconds=31),
    )

    assert snapshot.deliveries[0].state is ChannelDeliveryState.AMBIGUOUS
    assert snapshot.terminal is True
