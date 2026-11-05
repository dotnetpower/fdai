"""Fan-out routing and durable per-channel state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.notifications import (
    ChannelBinding,
    ChannelDeliveryClaim,
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    ChannelRegistry,
    DeliveryClaimStatus,
    InMemoryNotificationDeliveryStore,
    NotificationRouter,
    RouteOutcome,
    load_matrix_from_mapping,
)
from fdai.shared.providers.notifications import (
    ChannelAmbiguousError,
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


async def test_delivery_store_validation_and_claim_states() -> None:
    store = InMemoryNotificationDeliveryStore()
    naive_now = datetime(2026, 8, 27, 12, 0, 0)

    with pytest.raises(ValueError, match="audit_id MUST be non-empty"):
        await store.create_plan(
            audit_id="",
            target_channel_ids=("teams-ops",),
            excluded_channels={},
            now=NOW,
        )
    with pytest.raises(ValueError, match="timestamp MUST be timezone-aware"):
        await store.create_plan(
            audit_id="audit-tz",
            target_channel_ids=("teams-ops",),
            excluded_channels={},
            now=naive_now,
        )
    with pytest.raises(ValueError, match="target channel ids MUST be unique"):
        await store.create_plan(
            audit_id="audit-dup",
            target_channel_ids=("teams-ops", "teams-ops"),
            excluded_channels={},
            now=NOW,
        )

    await store.create_plan(
        audit_id="audit-states",
        target_channel_ids=("teams-ops", "email-oncall"),
        excluded_channels={},
        now=NOW,
    )

    with pytest.raises(ValueError, match="channel_id MUST be non-empty"):
        await store.claim(
            audit_id="audit-states",
            channel_id="",
            now=NOW,
            lease_seconds=30,
            max_attempts=2,
        )
    with pytest.raises(ValueError, match="bounds MUST be positive"):
        await store.claim(
            audit_id="audit-states",
            channel_id="teams-ops",
            now=NOW,
            lease_seconds=0,
            max_attempts=2,
        )
    with pytest.raises(KeyError, match="is not part of notification dispatch"):
        await store.claim(
            audit_id="audit-states",
            channel_id="missing-channel",
            now=NOW,
            lease_seconds=30,
            max_attempts=2,
        )

    first_claim = await store.claim(
        audit_id="audit-states",
        channel_id="teams-ops",
        now=NOW,
        lease_seconds=30,
        max_attempts=2,
    )
    assert first_claim.status is DeliveryClaimStatus.CLAIMED
    assert first_claim.record.token is not None

    in_progress = await store.claim(
        audit_id="audit-states",
        channel_id="teams-ops",
        now=NOW + timedelta(seconds=10),
        lease_seconds=30,
        max_attempts=2,
    )
    assert in_progress.status is DeliveryClaimStatus.IN_PROGRESS

    with pytest.raises(ValueError, match="result state is invalid"):
        await store.record_result(
            audit_id="audit-states",
            channel_id="teams-ops",
            token=first_claim.record.token,
            state=ChannelDeliveryState.PENDING,
            at=NOW,
        )
    with pytest.raises(ValueError, match="token MUST be non-empty"):
        await store.record_result(
            audit_id="audit-states",
            channel_id="teams-ops",
            token="",
            state=ChannelDeliveryState.DELIVERED,
            at=NOW,
        )
    with pytest.raises(ValueError, match="retry_after_seconds MUST be >= 0"):
        await store.record_result(
            audit_id="audit-states",
            channel_id="teams-ops",
            token=first_claim.record.token,
            state=ChannelDeliveryState.RETRYABLE_FAILED,
            at=NOW,
            retry_after_seconds=-1.0,
        )
    with pytest.raises(ValueError, match="positive confirmation timeout"):
        await store.record_result(
            audit_id="audit-states",
            channel_id="teams-ops",
            token=first_claim.record.token,
            state=ChannelDeliveryState.ACCEPTED,
            at=NOW,
            confirmation_timeout_seconds=0,
        )
    with pytest.raises(RuntimeError, match="claim token mismatch"):
        await store.record_result(
            audit_id="audit-states",
            channel_id="teams-ops",
            token="wrong-token",
            state=ChannelDeliveryState.DELIVERED,
            at=NOW,
        )

    await store.record_result(
        audit_id="audit-states",
        channel_id="teams-ops",
        token=first_claim.record.token,
        state=ChannelDeliveryState.RETRYABLE_FAILED,
        at=NOW,
        retry_after_seconds=20.0,
        error="transient error",
    )
    not_due_retry = await store.claim(
        audit_id="audit-states",
        channel_id="teams-ops",
        now=NOW + timedelta(seconds=5),
        lease_seconds=30,
        max_attempts=2,
    )
    assert not_due_retry.status is DeliveryClaimStatus.NOT_DUE

    second_claim = await store.claim(
        audit_id="audit-states",
        channel_id="teams-ops",
        now=NOW + timedelta(seconds=25),
        lease_seconds=30,
        max_attempts=2,
    )
    assert second_claim.status is DeliveryClaimStatus.CLAIMED
    assert second_claim.record.token is not None

    await store.record_result(
        audit_id="audit-states",
        channel_id="teams-ops",
        token=second_claim.record.token,
        state=ChannelDeliveryState.ACCEPTED,
        at=NOW + timedelta(seconds=25),
        confirmation_timeout_seconds=60,
    )
    not_due_accepted = await store.claim(
        audit_id="audit-states",
        channel_id="teams-ops",
        now=NOW + timedelta(seconds=30),
        lease_seconds=30,
        max_attempts=2,
    )
    assert not_due_accepted.status is DeliveryClaimStatus.NOT_DUE

    with pytest.raises(ValueError, match="publication failure error MUST be non-empty"):
        await store.record_publication_failure(
            audit_id="audit-states",
            channel_id="teams-ops",
            at=NOW + timedelta(seconds=31),
            error="",
        )
    with pytest.raises(RuntimeError, match="only an accepted notification delivery"):
        await store.record_publication_failure(
            audit_id="audit-states",
            channel_id="email-oncall",
            at=NOW + timedelta(seconds=31),
            error="not accepted yet",
        )

    failed_pub = await store.record_publication_failure(
        audit_id="audit-states",
        channel_id="teams-ops",
        at=NOW + timedelta(seconds=31),
        error="webhook callback failed",
    )
    assert failed_pub.state is ChannelDeliveryState.RETRYABLE_FAILED
    idempotent_failed_pub = await store.record_publication_failure(
        audit_id="audit-states",
        channel_id="teams-ops",
        at=NOW + timedelta(seconds=32),
        error="webhook callback failed",
    )
    assert idempotent_failed_pub == failed_pub

    expired_claim = await store.claim(
        audit_id="audit-states",
        channel_id="email-oncall",
        now=NOW,
        lease_seconds=10,
        max_attempts=2,
    )
    assert expired_claim.record.token is not None
    await store.record_result(
        audit_id="audit-states",
        channel_id="email-oncall",
        token=expired_claim.record.token,
        state=ChannelDeliveryState.ACCEPTED,
        at=NOW,
        confirmation_timeout_seconds=10,
    )
    terminal_claim = await store.claim(
        audit_id="audit-states",
        channel_id="email-oncall",
        now=NOW + timedelta(seconds=15),
        lease_seconds=10,
        max_attempts=2,
    )
    assert terminal_claim.status is DeliveryClaimStatus.TERMINAL
    assert terminal_claim.record.state is ChannelDeliveryState.AMBIGUOUS


async def test_router_validates_bounds_and_handles_fanout_exclusions() -> None:
    audit = InMemoryStateStore()
    sink = FakeHilEscalationSink()
    matrix = _matrix(
        "disabled-ch",
        "unconfigured-ch",
        "unresolved-ch",
        "bind-mismatch",
        "adapter-mismatch",
    )

    with pytest.raises(ValueError, match="notification delivery bounds are invalid"):
        NotificationRouter(
            matrix=matrix,
            registry=ChannelRegistry(),
            audit_store=audit,
            hil_sink=sink,
            max_parallelism=0,
        )

    bind_mismatch_ch = FakeTeamsChannel(
        channel_id="bind-mismatch",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    adapter_mismatch_ch = FakeEmailChannel(
        channel_id="adapter-mismatch",
        trust_tiers=frozenset({TrustTier.A4_DIGEST}),
    )
    registry = ChannelRegistry(
        channels={
            bind_mismatch_ch.channel_id: bind_mismatch_ch,
            adapter_mismatch_ch.channel_id: adapter_mismatch_ch,
        },
        bindings={
            "disabled-ch": ChannelBinding(channel_id="disabled-ch", enabled=False),
            "unconfigured-ch": ChannelBinding(channel_id="unconfigured-ch", configured=False),
            "unresolved-ch": ChannelBinding(
                channel_id="unresolved-ch",
                enabled=True,
                configured=True,
            ),
            "bind-mismatch": ChannelBinding(
                channel_id="bind-mismatch",
                trust_tiers=frozenset({TrustTier.A4_DIGEST}),
            ),
            "adapter-mismatch": ChannelBinding(
                channel_id="adapter-mismatch",
                trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            ),
        },
    )
    router = NotificationRouter(
        matrix=matrix,
        registry=registry,
        audit_store=audit,
        hil_sink=sink,
    )
    msg_without_audit_id = NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id="fanout-no-audit-id",
        title="Operational alert",
        body_markdown="Body",
    )

    result = await router.dispatch(msg_without_audit_id)

    assert result.outcome is RouteOutcome.NO_ELIGIBLE_CHANNELS
    assert result.excluded_channels == {
        "disabled-ch": "disabled",
        "unconfigured-ch": "configuration_invalid",
        "unresolved-ch": "unresolved",
        "bind-mismatch": "binding_trust_mismatch",
        "adapter-mismatch": "adapter_trust_mismatch",
    }
    assert len(list(sink.entries)) == 1


async def test_fanout_retries_soft_failures_and_handles_vanished_or_ambiguous_channels() -> None:
    store = InMemoryNotificationDeliveryStore()
    await store.create_plan(
        audit_id="audit-fanout-1",
        target_channel_ids=("vanished-ch", "soft-fail-ch", "ambiguous-ch"),
        excluded_channels={},
        now=NOW,
    )
    soft_fail_ch = FakeTeamsChannel(
        channel_id="soft-fail-ch",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    soft_fail_ch.arm_delivery_failures(1)

    class _AmbiguousChannel(FakeEmailChannel):
        async def send(self, message: NotificationMessage):  # type: ignore[override]
            raise ChannelAmbiguousError("transport timed out after request write")

    ambiguous_ch = _AmbiguousChannel(
        channel_id="ambiguous-ch",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    slept: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        slept.append(delay)

    router = NotificationRouter(
        matrix=_matrix("vanished-ch", "soft-fail-ch", "ambiguous-ch"),
        registry=ChannelRegistry(
            channels={
                soft_fail_ch.channel_id: soft_fail_ch,
                ambiguous_ch.channel_id: ambiguous_ch,
            }
        ),
        audit_store=InMemoryStateStore(),
        hil_sink=FakeHilEscalationSink(),
        delivery_store=store,
        max_attempts=2,
        retry_backoff_seconds=0.0,
        sleep=_fake_sleep,
    )
    result = await router.dispatch(_message())
    states = {item.channel_id: item.state for item in result.deliveries}
    assert states == {
        "vanished-ch": ChannelDeliveryState.ABANDONED,
        "soft-fail-ch": ChannelDeliveryState.DELIVERED,
        "ambiguous-ch": ChannelDeliveryState.AMBIGUOUS,
    }
    assert {r.channel_id for r in result.receipts} == {"soft-fail-ch", "ambiguous-ch"}

    # Also exercise positive retry_backoff_seconds + non-terminal FAILED_ALL snapshot.
    failing_ch = FakeTeamsChannel(
        channel_id="failing-ch",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    failing_ch.arm_delivery_failures(1)
    sink = FakeHilEscalationSink()
    backoff_router = NotificationRouter(
        matrix=_matrix("failing-ch"),
        registry=ChannelRegistry(channels={"failing-ch": failing_ch}),
        audit_store=InMemoryStateStore(),
        hil_sink=sink,
        max_attempts=1,
        retry_backoff_seconds=0.25,
        sleep=_fake_sleep,
    )
    failed_result = await backoff_router.dispatch(_message())
    assert failed_result.outcome is RouteOutcome.FAILED_ALL
    assert failed_result.terminal is False
    assert slept == [0.25]
    assert tuple(sink.entries) == ()


async def test_fanout_propagates_unexpected_tokenless_claim_error() -> None:
    class _TokenlessClaimStore(InMemoryNotificationDeliveryStore):
        async def claim(
            self,
            *,
            audit_id: str,
            channel_id: str,
            now: datetime,
            lease_seconds: int,
            max_attempts: int,
        ) -> ChannelDeliveryClaim:
            return ChannelDeliveryClaim(
                status=DeliveryClaimStatus.CLAIMED,
                record=ChannelDeliveryRecord(
                    channel_id=channel_id,
                    state=ChannelDeliveryState.SENDING,
                    attempts=1,
                    token=None,
                ),
            )

    teams = FakeTeamsChannel(
        channel_id="teams-ops",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    router, _, _ = _router(
        teams,
        FakeEmailChannel(channel_id="email-oncall"),
        delivery_store=_TokenlessClaimStore(),
    )
    with pytest.raises(RuntimeError, match="claimed notification delivery has no token"):
        await router.dispatch(_message())
