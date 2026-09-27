"""Real notification-channel adapters (httpx-based).

Each adapter implements exactly one of the seven Protocols in
:mod:`fdai.shared.providers.notifications`. They live under
``delivery/`` so ``core/`` cannot import them (enforced by
``scripts/quality/architecture/check-core-imports.sh``).

- :mod:`.teams` - Microsoft Teams Workflows webhook (Adaptive Card body).
- :mod:`.slack` - Slack incoming-webhook (Block Kit body).
- :mod:`.email` - Azure Communication Services Email REST API.
- :mod:`.webhook` - generic HMAC-signed HTTP POST.
- :mod:`.pagerduty` - PagerDuty Events API v2.
- :mod:`.sms` - Azure Communication Services SMS REST API.
- :mod:`.direct_line` - Bot Framework Direct Line custom channel (A2/A4 activity).

Every adapter accepts a live :class:`httpx.AsyncClient` at construction so
the composition root controls pooling + timeouts. The adapter itself
wraps every call in a bounded timeout, truncates response bodies (they
are untrusted), and translates non-2xx into
:class:`~fdai.shared.providers.notifications.ChannelDeliveryError`.
"""

from .bindings import (
    NOTIFICATION_TRUST_TIERS,
    NotificationBindingKind,
    NotificationBindingSpec,
    default_notification_bindings_from_env,
    parse_notification_bindings,
)
from .direct_line import (
    DIRECT_LINE_TRUST_TIERS,
    DirectLineConfig,
    DirectLineCredential,
    DirectLineCredentialProvider,
    DirectLineNotificationChannel,
    static_direct_line_credential,
)
from .direct_line_rendering import direct_line_idempotency_key, render_direct_line_payload
from .email import AzureCommunicationEmailChannel, AzureCommunicationEmailConfig
from .hil_sink import StateStoreHilEscalationSink
from .pagerduty import PagerDutyEventsV2Channel, PagerDutyEventsV2Config
from .receipt import (
    NotificationDeliveryReceiptApplier,
    NotificationReceiptRejectedError,
)
from .shadow_recorder import (
    ShadowDeliveryConflictError,
    StateStoreShadowDeliveryRecorder,
)
from .slack import SlackWebhookChannel, SlackWebhookConfig, render_slack_payload
from .sms import AzureCommunicationSmsChannel, AzureCommunicationSmsConfig
from .teams import (
    TeamsWebhookChannel,
    TeamsWebhookConfig,
    TeamsWorkflowAuthMode,
    render_teams_payload,
)
from .webhook import GenericWebhookChannel, GenericWebhookConfig

__all__ = [
    "DIRECT_LINE_TRUST_TIERS",
    "NOTIFICATION_TRUST_TIERS",
    "AzureCommunicationEmailChannel",
    "AzureCommunicationEmailConfig",
    "AzureCommunicationSmsChannel",
    "AzureCommunicationSmsConfig",
    "DirectLineConfig",
    "DirectLineCredential",
    "DirectLineCredentialProvider",
    "DirectLineNotificationChannel",
    "GenericWebhookChannel",
    "GenericWebhookConfig",
    "NotificationBindingKind",
    "NotificationBindingSpec",
    "NotificationDeliveryReceiptApplier",
    "NotificationReceiptRejectedError",
    "PagerDutyEventsV2Channel",
    "PagerDutyEventsV2Config",
    "SlackWebhookChannel",
    "SlackWebhookConfig",
    "ShadowDeliveryConflictError",
    "StateStoreHilEscalationSink",
    "StateStoreShadowDeliveryRecorder",
    "TeamsWebhookChannel",
    "TeamsWebhookConfig",
    "TeamsWorkflowAuthMode",
    "default_notification_bindings_from_env",
    "direct_line_idempotency_key",
    "parse_notification_bindings",
    "render_direct_line_payload",
    "render_slack_payload",
    "render_teams_payload",
    "static_direct_line_credential",
]
