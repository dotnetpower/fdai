"""Real notification-channel adapters (httpx-based).

Each adapter implements exactly one of the six Protocols in
:mod:`fdai.shared.providers.notifications`. They live under
``delivery/`` so ``core/`` cannot import them (enforced by
``scripts/quality/architecture/check-core-imports.sh``).

- :mod:`.teams` - Microsoft Teams Workflows webhook (Adaptive Card body).
- :mod:`.slack` - Slack incoming-webhook (Block Kit body).
- :mod:`.email` - Azure Communication Services Email REST API.
- :mod:`.webhook` - generic HMAC-signed HTTP POST.
- :mod:`.pagerduty` - PagerDuty Events API v2.
- :mod:`.sms` - Azure Communication Services SMS REST API.

Every adapter accepts a live :class:`httpx.AsyncClient` at construction so
the composition root controls pooling + timeouts. The adapter itself
wraps every call in a bounded timeout, truncates response bodies (they
are untrusted), and translates non-2xx into
:class:`~fdai.shared.providers.notifications.ChannelDeliveryError`.
"""

from .bindings import (
    NotificationBindingKind,
    NotificationBindingSpec,
    default_notification_bindings_from_env,
    parse_notification_bindings,
)
from .email import AzureCommunicationEmailChannel, AzureCommunicationEmailConfig
from .hil_sink import StateStoreHilEscalationSink
from .pagerduty import PagerDutyEventsV2Channel, PagerDutyEventsV2Config
from .receipt import (
    TeamsWorkflowReceiptConfig,
    TeamsWorkflowReceiptHandler,
    compute_receipt_signature,
)
from .slack import SlackWebhookChannel, SlackWebhookConfig
from .sms import AzureCommunicationSmsChannel, AzureCommunicationSmsConfig
from .teams import TeamsWebhookChannel, TeamsWebhookConfig, TeamsWorkflowAuthMode
from .webhook import GenericWebhookChannel, GenericWebhookConfig

__all__ = [
    "AzureCommunicationEmailChannel",
    "AzureCommunicationEmailConfig",
    "AzureCommunicationSmsChannel",
    "AzureCommunicationSmsConfig",
    "GenericWebhookChannel",
    "GenericWebhookConfig",
    "NotificationBindingKind",
    "NotificationBindingSpec",
    "PagerDutyEventsV2Channel",
    "PagerDutyEventsV2Config",
    "SlackWebhookChannel",
    "SlackWebhookConfig",
    "StateStoreHilEscalationSink",
    "TeamsWebhookChannel",
    "TeamsWebhookConfig",
    "TeamsWorkflowAuthMode",
    "TeamsWorkflowReceiptConfig",
    "TeamsWorkflowReceiptHandler",
    "compute_receipt_signature",
    "default_notification_bindings_from_env",
    "parse_notification_bindings",
]
