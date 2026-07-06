"""Real notification-channel adapters (httpx-based).

Each adapter implements exactly one of the six Protocols in
:mod:`aiopspilot.shared.providers.notifications`. They live under
``delivery/`` so ``core/`` cannot import them (enforced by
``scripts/check-core-imports.sh``).

- :mod:`.teams` — Microsoft Teams incoming-webhook (Adaptive Card body).
- :mod:`.slack` — Slack incoming-webhook (Block Kit body).
- :mod:`.email` — Azure Communication Services Email REST API.
- :mod:`.webhook` — generic HMAC-signed HTTP POST.
- :mod:`.pagerduty` — PagerDuty Events API v2.
- :mod:`.sms` — Azure Communication Services SMS REST API.

Every adapter accepts a live :class:`httpx.AsyncClient` at construction so
the composition root controls pooling + timeouts. The adapter itself
wraps every call in a bounded timeout, truncates response bodies (they
are untrusted), and translates non-2xx into
:class:`~aiopspilot.shared.providers.notifications.ChannelDeliveryError`.
"""

from .email import AzureCommunicationEmailChannel, AzureCommunicationEmailConfig
from .pagerduty import PagerDutyEventsV2Channel, PagerDutyEventsV2Config
from .slack import SlackWebhookChannel, SlackWebhookConfig
from .sms import AzureCommunicationSmsChannel, AzureCommunicationSmsConfig
from .teams import TeamsWebhookChannel, TeamsWebhookConfig
from .webhook import GenericWebhookChannel, GenericWebhookConfig

__all__ = [
    "AzureCommunicationEmailChannel",
    "AzureCommunicationEmailConfig",
    "AzureCommunicationSmsChannel",
    "AzureCommunicationSmsConfig",
    "GenericWebhookChannel",
    "GenericWebhookConfig",
    "PagerDutyEventsV2Channel",
    "PagerDutyEventsV2Config",
    "SlackWebhookChannel",
    "SlackWebhookConfig",
    "TeamsWebhookChannel",
    "TeamsWebhookConfig",
]
