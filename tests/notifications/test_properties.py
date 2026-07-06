"""Fake channel + adapter property coverage tests."""

from __future__ import annotations

import httpx
import pytest

from aiopspilot.delivery.notifications import (
    AzureCommunicationEmailChannel,
    AzureCommunicationEmailConfig,
    AzureCommunicationSmsChannel,
    AzureCommunicationSmsConfig,
    GenericWebhookChannel,
    GenericWebhookConfig,
    PagerDutyEventsV2Channel,
    PagerDutyEventsV2Config,
    SlackWebhookChannel,
    SlackWebhookConfig,
    TeamsWebhookChannel,
    TeamsWebhookConfig,
)
from aiopspilot.shared.providers.notifications import (
    ChannelDeliveryError,
    ChannelKind,
    NotificationMessage,
    TrustTier,
)
from aiopspilot.shared.providers.testing.notifications import (
    FakeEmailChannel,
    FakePagerDutyChannel,
    FakeSlackChannel,
    FakeSmsChannel,
    FakeTeamsChannel,
    FakeWebhookChannel,
)


class TestFakeArmRaisesCustomMessage:
    async def test_custom_raise_message_is_used(self) -> None:
        fake = FakeSlackChannel(channel_id="s", trust_tiers=frozenset())
        fake.arm_raises(1, message="custom boom")
        message = NotificationMessage(
            category="x",
            trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
            correlation_id="c",
            title="t",
            body_markdown="b",
        )
        with pytest.raises(ChannelDeliveryError, match="custom boom"):
            await fake.send(message)


class TestAdapterProperties:
    """Ensure every adapter exposes the ``channel_id`` / ``trust_tiers``
    accessors the router relies on for structural typing.
    """

    def test_teams(self) -> None:
        cfg = TeamsWebhookConfig(
            channel_id="t-id",
            webhook_url="https://x/",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        )
        adapter = TeamsWebhookChannel(config=cfg, http_client=httpx.AsyncClient())
        assert adapter.channel_id == "t-id"
        assert adapter.trust_tiers == frozenset({TrustTier.A2_OPERATIONAL_ALERT})
        assert adapter.channel_kind is ChannelKind.TEAMS

    def test_slack(self) -> None:
        cfg = SlackWebhookConfig(
            channel_id="s-id",
            webhook_url="https://x/",
            trust_tiers=frozenset({TrustTier.A1_HIL_APPROVAL}),
        )
        adapter = SlackWebhookChannel(config=cfg, http_client=httpx.AsyncClient())
        assert adapter.channel_id == "s-id"
        assert adapter.trust_tiers == frozenset({TrustTier.A1_HIL_APPROVAL})
        assert adapter.channel_kind is ChannelKind.SLACK

    def test_email(self) -> None:
        cfg = AzureCommunicationEmailConfig(
            channel_id="e-id",
            endpoint="https://acs/",
            recipient_addresses=("x@example.com",),
            trust_tiers=frozenset({TrustTier.A4_DIGEST}),
        )
        adapter = AzureCommunicationEmailChannel(config=cfg, http_client=httpx.AsyncClient())
        assert adapter.channel_id == "e-id"
        assert adapter.trust_tiers == frozenset({TrustTier.A4_DIGEST})
        assert adapter.channel_kind is ChannelKind.EMAIL

    def test_webhook(self) -> None:
        cfg = GenericWebhookConfig(
            channel_id="w-id",
            url="https://x/hook",
            hmac_secret="s",  # noqa: S106 — test-only literal
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        )
        adapter = GenericWebhookChannel(config=cfg, http_client=httpx.AsyncClient())
        assert adapter.channel_id == "w-id"
        assert adapter.trust_tiers == frozenset({TrustTier.A2_OPERATIONAL_ALERT})
        assert adapter.channel_kind is ChannelKind.WEBHOOK

    def test_pagerduty(self) -> None:
        cfg = PagerDutyEventsV2Config(
            channel_id="p-id",
            routing_key="rk",
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        )
        adapter = PagerDutyEventsV2Channel(config=cfg, http_client=httpx.AsyncClient())
        assert adapter.channel_id == "p-id"
        assert adapter.trust_tiers == frozenset({TrustTier.A2_OPERATIONAL_ALERT})
        assert adapter.channel_kind is ChannelKind.PAGERDUTY

    def test_sms(self) -> None:
        cfg = AzureCommunicationSmsConfig(
            channel_id="sms-id",
            endpoint="https://acs/",
            from_phone_number="+1",
            to_phone_numbers=("+2",),
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        )
        adapter = AzureCommunicationSmsChannel(config=cfg, http_client=httpx.AsyncClient())
        assert adapter.channel_id == "sms-id"
        assert adapter.trust_tiers == frozenset({TrustTier.A2_OPERATIONAL_ALERT})
        assert adapter.channel_kind is ChannelKind.SMS


class TestFakeChannelKinds:
    def test_kinds_are_set(self) -> None:
        assert FakeTeamsChannel(channel_id="t").channel_kind is ChannelKind.TEAMS
        assert FakeSlackChannel(channel_id="s").channel_kind is ChannelKind.SLACK
        assert FakeEmailChannel(channel_id="e").channel_kind is ChannelKind.EMAIL
        assert FakeWebhookChannel(channel_id="w").channel_kind is ChannelKind.WEBHOOK
        assert FakePagerDutyChannel(channel_id="p").channel_kind is ChannelKind.PAGERDUTY
        assert FakeSmsChannel(channel_id="sm").channel_kind is ChannelKind.SMS
