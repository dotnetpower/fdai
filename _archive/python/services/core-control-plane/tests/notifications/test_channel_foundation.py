"""Focused tests for the A2/A4 channel-foundation contracts (issue #422).

Coverage plan
-------------

- **Capability-state contract** - :class:`ChannelCapabilityState` computes
  ``ready`` from the three independent flags, renders the same
  source-attributed readiness shape the Settings projection uses, and
  rejects an empty ``channel_id``.
- **Presentation boundary** - :func:`render_presentation` fails closed on
  unsupported interactive content (matched case-insensitively), oversized
  title/body/link/metadata fields (including the metadata *key* length, not
  only its value), a non-``https`` link scheme, and secret-like text
  (checked in metadata keys as well as values); it returns an immutable
  envelope - including an immutable ``metadata`` mapping - for a bounded,
  clean message.
- **Shadow delivery** - :class:`ShadowNotificationChannel` renders and
  durably records a message without any network call, propagates a
  presentation rejection instead of recording partial content, rejects a
  naive (timezone-less) clock result, and is idempotent: a repeated
  ``send()`` for the same ``correlation_id + audit_id + category`` records
  exactly one entry and returns the same ``provider_message_id``, while a
  different channel or identity tuple produces a different one.
- **Router integration** - :class:`~fdai.core.notifications.NotificationRouter`
  reaches deterministic outcomes for an unavailable provider, a shadowed
  provider, a rejected presentation, and a fallback chain, always writing
  exactly one audit entry per :meth:`~fdai.core.notifications.NotificationRouter.dispatch`
  call; a repeated fan-out dispatch for the same ``audit_id`` never re-sends
  an already-terminal target (idempotent redelivery).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest
from fdai.core.notifications import (
    ChannelDeliveryState,
    ChannelRegistry,
    InMemoryShadowDeliveryRecorder,
    NotificationMatrix,
    NotificationRouter,
    OnAllFailAction,
    RouteOutcome,
    ShadowNotificationChannel,
    load_matrix_from_mapping,
)
from fdai.shared.providers.notifications import (
    ChannelCapabilityState,
    ChannelKind,
    ChannelMode,
    ChannelUnavailableError,
    DeliveryReceipt,
    Link,
    NotificationChannel,
    NotificationMessage,
    PresentationRejectedError,
    Severity,
    TrustTier,
    render_presentation,
)
from fdai.shared.providers.notifications.presentation import PresentationLimits
from fdai.shared.providers.testing.notifications import (
    FakeEmailChannel,
    FakeHilEscalationSink,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _message(
    *,
    title: str = "DLQ depth high",
    body_markdown: str = "Depth = 42 (threshold 10).",
    links: tuple[Link, ...] = (),
    metadata: dict[str, str] | None = None,
    audit_id: str | None = "audit-foundation-1",
) -> NotificationMessage:
    return NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id="cid-foundation-1",
        title=title,
        body_markdown=body_markdown,
        severity=Severity.ERROR,
        audit_id=audit_id,
        links=links,
        metadata=metadata or {},
    )


def _secret_like_fixture() -> str:
    return ": ".join(("api_key", "synthetic-value"))


def _failover_matrix(primary: str, *fallback: str) -> NotificationMatrix:
    return load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "operational_alert",
                "routes": {
                    "operational_alert": {
                        "trust_tier": TrustTier.A2_OPERATIONAL_ALERT.value,
                        "primary": primary,
                        "fallback": list(fallback),
                        "on_all_fail": OnAllFailAction.HIL_ESCALATE.value,
                    }
                },
            }
        }
    )


def _fanout_matrix(*channels: str) -> NotificationMatrix:
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


@dataclass
class _UnavailableChannel:
    """Minimal :class:`NotificationChannel` that is always unreachable."""

    channel_kind: ChannelKind
    channel_id: str
    trust_tiers: frozenset[TrustTier]

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        raise ChannelUnavailableError("fake: provider unreachable")


# ---------------------------------------------------------------------------
# Capability-state contract
# ---------------------------------------------------------------------------


class TestChannelCapabilityState:
    def test_ready_requires_all_three_flags(self) -> None:
        ready = ChannelCapabilityState(
            channel_id="teams-ops-prd",
            available=True,
            enabled=True,
            configured=True,
            mode=ChannelMode.ENFORCE,
        )
        assert ready.ready is True

        unavailable = ChannelCapabilityState(
            channel_id="teams-ops-prd", available=False, enabled=True, configured=True
        )
        disabled = ChannelCapabilityState(
            channel_id="teams-ops-prd", available=True, enabled=False, configured=True
        )
        unconfigured = ChannelCapabilityState(
            channel_id="teams-ops-prd", available=True, enabled=True, configured=False
        )
        assert unavailable.ready is False
        assert disabled.ready is False
        assert unconfigured.ready is False

    def test_readiness_row_matches_settings_shape_when_ready(self) -> None:
        state = ChannelCapabilityState(
            channel_id="teams-ops-prd",
            available=True,
            enabled=True,
            configured=True,
            mode=ChannelMode.SHADOW,
        )
        row = state.to_readiness_row(source="core-control-plane")
        assert row == {
            "key": "teams-ops-prd",
            "source": "core-control-plane",
            "observed": True,
            "configured": True,
            "ready": True,
            "mode": "shadow",
            "reason": None,
        }

    def test_readiness_row_reports_disabled_mode_and_reason_when_not_ready(self) -> None:
        state = ChannelCapabilityState(
            channel_id="teams-ops-prd",
            available=True,
            enabled=False,
            configured=True,
        )
        row = state.to_readiness_row(source="core-control-plane")
        assert row["ready"] is False
        assert row["mode"] == "disabled"
        assert row["reason"] == "disabled by operator"

    def test_rejects_empty_channel_id(self) -> None:
        with pytest.raises(ValueError, match="channel_id"):
            ChannelCapabilityState(
                channel_id="",
                available=True,
                enabled=True,
                configured=True,
            )


# ---------------------------------------------------------------------------
# Presentation boundary (pre-render, fail-closed)
# ---------------------------------------------------------------------------


class TestRenderPresentation:
    def test_accepts_bounded_message_and_returns_immutable_envelope(self) -> None:
        message = _message(links=(Link(label="Runbook", url="https://example.com/runbook"),))
        envelope = render_presentation(message, channel_id="teams-ops-prd")
        assert envelope.channel_id == "teams-ops-prd"
        assert envelope.title == message.title
        assert envelope.body_markdown == message.body_markdown
        assert envelope.links == message.links
        with pytest.raises(AttributeError):
            envelope.title = "mutated"  # type: ignore[misc]

    def test_envelope_metadata_is_immutable(self) -> None:
        message = _message(metadata={"tenant": "contoso"})
        envelope = render_presentation(message, channel_id="teams-ops-prd")
        with pytest.raises(TypeError):
            envelope.metadata["tenant"] = "mutated"  # type: ignore[index]

    def test_rejects_unsupported_interactive_metadata(self) -> None:
        message = _message(metadata={"actions": '[{"type": "button"}]'})
        with pytest.raises(PresentationRejectedError, match="interactive"):
            render_presentation(message, channel_id="teams-ops-prd")

    def test_rejects_unsupported_interactive_metadata_regardless_of_key_case(self) -> None:
        message = _message(metadata={"Actions": '[{"type": "button"}]'})
        with pytest.raises(PresentationRejectedError, match="interactive"):
            render_presentation(message, channel_id="teams-ops-prd")

        message = _message(metadata={"QUICK_REPLIES": "yes,no"})
        with pytest.raises(PresentationRejectedError, match="interactive"):
            render_presentation(message, channel_id="teams-ops-prd")

    def test_rejects_oversized_title(self) -> None:
        message = _message(title="x" * 301)
        with pytest.raises(PresentationRejectedError, match="title"):
            render_presentation(message, channel_id="teams-ops-prd")

    def test_rejects_oversized_body(self) -> None:
        message = _message(body_markdown="x" * 4001)
        with pytest.raises(PresentationRejectedError, match="body"):
            render_presentation(message, channel_id="teams-ops-prd")

    def test_rejects_too_many_links(self) -> None:
        message = _message(
            links=tuple(Link(label=f"L{i}", url=f"https://example.com/{i}") for i in range(6))
        )
        with pytest.raises(PresentationRejectedError, match="link count"):
            render_presentation(message, channel_id="teams-ops-prd")

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "http://example.com/runbook",
            "file:///etc/passwd",
        ],
    )
    def test_rejects_non_https_link_schemes(self, url: str) -> None:
        message = _message(links=(Link(label="L", url=url),))
        with pytest.raises(PresentationRejectedError, match="https"):
            render_presentation(message, channel_id="teams-ops-prd")

    def test_accepts_https_link_regardless_of_scheme_case(self) -> None:
        message = _message(links=(Link(label="Runbook", url="HTTPS://example.com/runbook"),))
        envelope = render_presentation(message, channel_id="teams-ops-prd")
        assert envelope.links[0].url == "HTTPS://example.com/runbook"

    def test_rejects_oversized_metadata_key(self) -> None:
        message = _message(metadata={"x" * 65: "short"})
        with pytest.raises(PresentationRejectedError, match="metadata key"):
            render_presentation(message, channel_id="teams-ops-prd")

    def test_rejects_secret_like_metadata_key(self) -> None:
        message = _message(metadata={_secret_like_fixture(): "unrelated"})
        with pytest.raises(PresentationRejectedError, match="secret-like"):
            render_presentation(message, channel_id="teams-ops-prd")

    def test_rejects_secret_like_body(self) -> None:
        message = _message(body_markdown=_secret_like_fixture())
        with pytest.raises(PresentationRejectedError, match="secret-like"):
            render_presentation(message, channel_id="teams-ops-prd")

    def test_rejects_secret_like_link_url(self) -> None:
        message = _message(
            links=(Link(label="Signed", url="https://example.com/blob?sig=abcdef0123456789"),)
        )
        with pytest.raises(PresentationRejectedError, match="secret-like"):
            render_presentation(message, channel_id="teams-ops-prd")

    def test_limits_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            PresentationLimits(max_title_chars=0)


# ---------------------------------------------------------------------------
# Shadow delivery: render + record, no network
# ---------------------------------------------------------------------------


class TestShadowNotificationChannel:
    async def test_send_records_bounded_envelope_and_returns_delivered_receipt(self) -> None:
        recorder = InMemoryShadowDeliveryRecorder()
        channel = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-shadow",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
        )

        receipt = await channel.send(_message())

        assert receipt.delivered is True
        assert receipt.accepted is False
        assert receipt.provider_message_id is not None
        assert receipt.provider_message_id.startswith("shadow:")
        assert len(recorder.entries) == 1
        recorded = recorder.entries[0]
        assert recorded.channel_id == "teams-ops-shadow"
        assert recorded.envelope.title == "DLQ depth high"

    async def test_send_propagates_rejection_and_records_nothing(self) -> None:
        recorder = InMemoryShadowDeliveryRecorder()
        channel = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-shadow",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
        )

        with pytest.raises(PresentationRejectedError):
            await channel.send(_message(body_markdown="password: hunter2-shhh-do-not-print"))

        assert recorder.entries == ()

    async def test_repeated_send_for_same_identity_is_idempotent(self) -> None:
        """A re-issued send for the same correlation_id + audit_id + category
        MUST NOT create a duplicate record - channels-and-notifications.md § 5."""
        recorder = InMemoryShadowDeliveryRecorder()
        channel = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-shadow",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
        )
        message = _message()

        first = await channel.send(message)
        second = await channel.send(message)

        assert first.provider_message_id == second.provider_message_id
        assert len(recorder.entries) == 1

    async def test_record_id_varies_by_channel_correlation_audit_and_category(self) -> None:
        recorder = InMemoryShadowDeliveryRecorder()
        channel = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-shadow",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
        )
        other_channel = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-shadow-2",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
        )

        by_channel = await channel.send(_message())
        by_other_channel = await other_channel.send(_message())
        by_correlation = await channel.send(
            NotificationMessage(
                category="operational_alert",
                trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
                correlation_id="cid-foundation-2",
                title="DLQ depth high",
                body_markdown="Depth = 42 (threshold 10).",
                severity=Severity.ERROR,
                audit_id="audit-foundation-1",
            )
        )

        assert len({by_channel.provider_message_id, by_other_channel.provider_message_id}) == 2
        assert len({by_channel.provider_message_id, by_correlation.provider_message_id}) == 2
        assert len(recorder.entries) == 3

    async def test_send_rejects_naive_clock(self) -> None:
        recorder = InMemoryShadowDeliveryRecorder()
        channel = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-shadow",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
            clock=lambda: datetime(2026, 9, 9, 0, 0, 0),  # naive - no tzinfo
        )

        with pytest.raises(ValueError, match="timezone-aware"):
            await channel.send(_message())

        assert recorder.entries == ()


# ---------------------------------------------------------------------------
# Router integration: unavailable / shadowed / rejected / fallback / idempotent
# ---------------------------------------------------------------------------


class TestRouterUnavailableProvider:
    async def test_unavailable_primary_falls_back_deterministically(self) -> None:
        primary = _UnavailableChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-prd",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        )
        fallback = FakeEmailChannel(
            channel_id="email-oncall",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        )
        audit = InMemoryStateStore()
        sink = FakeHilEscalationSink()
        channels: dict[str, NotificationChannel] = {
            primary.channel_id: primary,
            fallback.channel_id: fallback,
        }
        router = NotificationRouter(
            matrix=_failover_matrix("teams-ops-prd", "email-oncall"),
            registry=ChannelRegistry(channels=channels),
            audit_store=audit,
            hil_sink=sink,
        )

        result = await router.dispatch(_message())

        assert result.outcome is RouteOutcome.DELIVERED_ON_FALLBACK
        assert result.delivered_channel_id == "email-oncall"
        assert tuple(sink.entries) == ()
        assert len(list(audit.audit_entries)) == 1


class TestRouterShadowedDelivery:
    async def test_shadowed_primary_delivers_without_network_with_one_audit_entry(self) -> None:
        recorder = InMemoryShadowDeliveryRecorder()
        shadow = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-prd",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
        )
        audit = InMemoryStateStore()
        sink = FakeHilEscalationSink()
        router = NotificationRouter(
            matrix=_failover_matrix("teams-ops-prd"),
            registry=ChannelRegistry(channels={shadow.channel_id: shadow}),
            audit_store=audit,
            hil_sink=sink,
        )

        result = await router.dispatch(_message())

        assert result.outcome is RouteOutcome.DELIVERED
        assert result.delivered_channel_id == "teams-ops-prd"
        assert len(recorder.entries) == 1
        assert tuple(sink.entries) == ()
        assert len(list(audit.audit_entries)) == 1

    async def test_shadowed_fanout_target_reaches_delivered_all(self) -> None:
        recorder = InMemoryShadowDeliveryRecorder()
        shadow = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-prd",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
        )
        email = FakeEmailChannel(
            channel_id="email-oncall",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        )
        audit = InMemoryStateStore()
        sink = FakeHilEscalationSink()
        channels: dict[str, NotificationChannel] = {
            shadow.channel_id: shadow,
            email.channel_id: email,
        }
        router = NotificationRouter(
            matrix=_fanout_matrix("teams-ops-prd", "email-oncall"),
            registry=ChannelRegistry(channels=channels),
            audit_store=audit,
            hil_sink=sink,
        )

        result = await router.dispatch(_message())

        assert result.outcome is RouteOutcome.DELIVERED_ALL
        assert {item.state for item in result.deliveries} == {ChannelDeliveryState.DELIVERED}
        assert len(recorder.entries) == 1
        assert len(email.records) == 1


class TestRouterRejectedPresentation:
    async def test_rejected_primary_falls_back_deterministically(self) -> None:
        recorder = InMemoryShadowDeliveryRecorder()
        shadow = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-prd",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
        )
        fallback = FakeEmailChannel(
            channel_id="email-oncall",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        )
        audit = InMemoryStateStore()
        sink = FakeHilEscalationSink()
        channels: dict[str, NotificationChannel] = {
            shadow.channel_id: shadow,
            fallback.channel_id: fallback,
        }
        router = NotificationRouter(
            matrix=_failover_matrix("teams-ops-prd", "email-oncall"),
            registry=ChannelRegistry(channels=channels),
            audit_store=audit,
            hil_sink=sink,
        )
        unsafe_message = _message(body_markdown="client_secret: super-sensitive-value-123456")

        result = await router.dispatch(unsafe_message)

        assert result.outcome is RouteOutcome.DELIVERED_ON_FALLBACK
        assert result.delivered_channel_id == "email-oncall"
        assert recorder.entries == ()
        assert len(list(audit.audit_entries)) == 1


class TestRouterFanoutIdempotency:
    async def test_repeated_dispatch_for_same_audit_id_never_resends_terminal_target(
        self,
    ) -> None:
        recorder = InMemoryShadowDeliveryRecorder()
        shadow = ShadowNotificationChannel(
            channel_kind=ChannelKind.TEAMS,
            channel_id="teams-ops-prd",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=recorder,
        )
        email = FakeEmailChannel(
            channel_id="email-oncall",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        )
        audit = InMemoryStateStore()
        sink = FakeHilEscalationSink()
        channels: dict[str, NotificationChannel] = {
            shadow.channel_id: shadow,
            email.channel_id: email,
        }
        router = NotificationRouter(
            matrix=_fanout_matrix("teams-ops-prd", "email-oncall"),
            registry=ChannelRegistry(channels=channels),
            audit_store=audit,
            hil_sink=sink,
        )
        message = _message(audit_id="audit-idempotent-1")

        first = await router.dispatch(message)
        second = await router.dispatch(message)

        assert first.outcome is RouteOutcome.DELIVERED_ALL
        assert second.outcome is RouteOutcome.DELIVERED_ALL
        assert first.target_channel_ids == second.target_channel_ids
        # The underlying channels were sent to exactly once each, even
        # though dispatch() ran twice for the same audit_id.
        assert len(recorder.entries) == 1
        assert len(email.records) == 1
        # Every dispatch() call still writes exactly one audit entry.
        assert len(list(audit.audit_entries)) == 2
