"""Six typed Protocols - one per channel vendor.

They share the same shape (``send(NotificationMessage) → DeliveryReceipt``)
but stay distinct types so the router's channel registry can enforce
kind ↔ id agreement at binding time. Concrete adapters MUST also expose
the ``channel_kind`` attribute of the matching :class:`ChannelKind`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .base import DeliveryReceipt, NotificationMessage, TrustTier


@runtime_checkable
class TeamsChannel(Protocol):
    """Microsoft Teams channel (Adaptive Cards, bot connector, Graph)."""

    channel_id: str
    trust_tiers: frozenset[TrustTier]

    async def send(self, message: NotificationMessage) -> DeliveryReceipt: ...


@runtime_checkable
class SlackChannel(Protocol):
    """Slack incoming-webhook / Web-API channel."""

    channel_id: str
    trust_tiers: frozenset[TrustTier]

    async def send(self, message: NotificationMessage) -> DeliveryReceipt: ...


@runtime_checkable
class EmailChannel(Protocol):
    """SMTP or Azure Communication Services Email channel."""

    channel_id: str
    trust_tiers: frozenset[TrustTier]

    async def send(self, message: NotificationMessage) -> DeliveryReceipt: ...


@runtime_checkable
class WebhookChannel(Protocol):
    """Generic outbound webhook (HMAC-signed HTTP POST)."""

    channel_id: str
    trust_tiers: frozenset[TrustTier]

    async def send(self, message: NotificationMessage) -> DeliveryReceipt: ...


@runtime_checkable
class PagerDutyChannel(Protocol):
    """PagerDuty Events API v2 channel (`trigger` action)."""

    channel_id: str
    trust_tiers: frozenset[TrustTier]

    async def send(self, message: NotificationMessage) -> DeliveryReceipt: ...


@runtime_checkable
class SmsChannel(Protocol):
    """SMS channel (default adapter: Azure Communication Services SMS)."""

    channel_id: str
    trust_tiers: frozenset[TrustTier]

    async def send(self, message: NotificationMessage) -> DeliveryReceipt: ...


__all__ = [
    "EmailChannel",
    "PagerDutyChannel",
    "SlackChannel",
    "SmsChannel",
    "TeamsChannel",
    "WebhookChannel",
]
