"""Notification-channel Protocols (Teams / Slack / Email / Webhook / PagerDuty / SMS).

Realizes the ``Channel`` contract in
[`docs/roadmap/interfaces/channels-and-notifications.md`](../../../../../docs/roadmap/interfaces/channels-and-notifications.md).
``core/`` sees only these Protocols and the router in
:mod:`fdai.core.notifications`; vendor SDKs (httpx, SMTP, ACS) sit
behind the concrete adapters under :mod:`fdai.delivery.notifications`.

Design points
-------------

- **One shape per channel, six typed Protocols.** Every adapter answers
  a single ``send(NotificationMessage) -> DeliveryReceipt`` call. Six
  Protocols keep the DI matrix statically typed - the router registers a
  ``TeamsChannel`` under the ``teams-*`` channel-ids and refuses to bind
  an :class:`EmailChannel` there.
- **Trust-tier lives on the message.** Every :class:`NotificationMessage`
  carries a :class:`TrustTier` (A1..A4) so the router can enforce the
  category-⊆-channel.categories rule without vendor knowledge.
- **Adapters never authorize.** ``awaitDecision`` (approval callback) is
  out of scope for the P1 router; ``send`` is send-only. Approval flows
  land in a later phase and re-enter through ``fdai-api``, matching
  the contract in the design doc.
- **Fakes ship in :mod:`~fdai.shared.providers.testing.notifications`**
  so both the router unit tests and downstream forks reuse them.
"""

from .base import (
    ChannelDeliveryError,
    ChannelKind,
    ChannelUnavailableError,
    DeliveryReceipt,
    HilEscalationSink,
    Link,
    NotificationChannel,
    NotificationMessage,
    Severity,
    TrustTier,
)
from .channels import (
    EmailChannel,
    PagerDutyChannel,
    SlackChannel,
    SmsChannel,
    TeamsChannel,
    WebhookChannel,
)

__all__ = [
    "ChannelDeliveryError",
    "ChannelKind",
    "ChannelUnavailableError",
    "DeliveryReceipt",
    "EmailChannel",
    "HilEscalationSink",
    "Link",
    "NotificationChannel",
    "NotificationMessage",
    "PagerDutyChannel",
    "Severity",
    "SlackChannel",
    "SmsChannel",
    "TeamsChannel",
    "TrustTier",
    "WebhookChannel",
]
