"""Shared types for the notification channel Protocols.

Kept vendor-neutral so ``core/`` and every adapter agree on the message
shape without pulling in httpx / SMTP libraries at import time.

Trust tiers (A1..A4) mirror the categories in
[`docs/roadmap/interfaces/channels-and-notifications.md § 3`]
(../../../../../docs/roadmap/interfaces/channels-and-notifications.md#3-categories-a1a4).
The router uses them to enforce category-⊆-channel.categories on every
dispatch and to preserve trust on fallback (§6 of the same doc).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ChannelKind(StrEnum):
    """Concrete channel vendors implemented in P1.

    The router indexes adapters by :class:`ChannelKind` so a routing
    entry can name a channel-id (``teams-hil-prd``) and the router
    resolves it to a bound adapter of the correct kind. Values are the
    strings that appear in ``config/notifications-matrix.yaml``.
    """

    TEAMS = "teams"
    SLACK = "slack"
    EMAIL = "email"
    WEBHOOK = "webhook"
    PAGERDUTY = "pagerduty"
    SMS = "sms"


class TrustTier(StrEnum):
    """Auth strength required by the message's purpose.

    Values are the ``A1``..``A4`` categories from
    :doc:`channels-and-notifications`. The router refuses to send an
    A1 message on a channel whose :attr:`NotificationChannel.trust_tiers`
    does not include A1 (send-only email / SMS / webhook / pager).
    """

    A1_HIL_APPROVAL = "a1_hil_approval"
    A2_OPERATIONAL_ALERT = "a2_operational_alert"
    A3_CHAT_COMMAND = "a3_chat_command"
    A4_DIGEST = "a4_digest"


class Severity(StrEnum):
    """Message severity - informational, mapped from the Adaptive-Card /
    Block-Kit colour palette. Vendor-neutral so the adapter picks the
    right visual on its side.
    """

    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Link:
    """One labelled hyperlink surfaced in the message body / card.

    A2/A4 messages carry links only - never inline action buttons - so
    every actionable path re-enters through :mod:`fdai-api` where
    it can be authenticated.
    """

    label: str
    url: str


class ChannelDeliveryError(RuntimeError):
    """Raised by an adapter when a single delivery attempt fails.

    Wraps the vendor-side error text (already truncated + secret-free)
    so the router can log and try the next fallback without knowing
    HTTP / SMTP details.
    """


class ChannelUnavailableError(ChannelDeliveryError):
    """Delivery-error subclass: adapter is up but currently unreachable.

    The router treats this the same as a plain delivery error but keeps
    the type so telemetry can distinguish "transient network" from
    "malformed payload" without re-parsing an error string.
    """


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    """Vendor-neutral payload every channel adapter accepts.

    Frozen: an adapter cannot rewrite the message between the router's
    audit-write and the actual send. All customer-identifying values MUST
    already be redacted by the caller (§1.5 in the design doc).
    """

    category: str
    """Semantic key the router looks up in the routing matrix
    (e.g. ``hil_approval``, ``operational_alert``, ``digest.shadow_daily``,
    ``chat_command_response``). Free-form so a fork can add its own
    digest names without editing core."""

    trust_tier: TrustTier
    """A1..A4 - enforced by the router against the channel's declared
    :attr:`NotificationChannel.trust_tiers`."""

    correlation_id: str
    """Stable id from the source event / action / digest run - used both
    for audit correlation and for adapter-side idempotency."""

    title: str
    body_markdown: str
    """Pre-redacted Markdown. Adapters MAY translate to Adaptive Card /
    Block Kit / plain-text; they MUST NOT add fresh content."""

    severity: Severity = Severity.INFO
    audit_id: str | None = None
    links: tuple[Link, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    """Adapter-neutral k/v pairs (tenant label, digest run id, ...). Never
    carries secrets."""

    template_key: str | None = None
    """Optional catalog key for L2 localization (see
    ``core/notifications/renderer``). When set, the router renders
    :attr:`title` / :attr:`body_markdown` from this key + :attr:`params` in the
    destination channel's locale. The baked :attr:`title` / :attr:`body_markdown`
    remain the English source used for the audit entry and as the fallback."""

    params: Mapping[str, str] = field(default_factory=dict)
    """L0 values substituted verbatim into the localized template (decision
    word, rule ids, resource type, mode). Never translated, so the rendered
    message differs across locales only in its labels."""


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """One adapter's response for a single send attempt.

    ``delivered=False`` is a soft failure - the router will try the next
    fallback. Hard failures raise :class:`ChannelDeliveryError` so the
    router can distinguish "adapter said the send didn't stick" from
    "adapter never got that far".
    """

    channel_kind: ChannelKind
    channel_id: str
    delivered: bool
    provider_message_id: str | None = None
    """Vendor-side id (Teams `messageId`, Slack `ts`, PagerDuty `dedup_key`).
    Opaque to core."""

    error: str | None = None
    """Human-readable reason when ``delivered=False``. Free of secrets;
    already truncated by the adapter."""


@runtime_checkable
class NotificationChannel(Protocol):
    """Base contract every channel Protocol conforms to.

    Six vendor-specific Protocols
    (:class:`TeamsChannel`, :class:`SlackChannel`, ...) narrow this one
    so the router can enforce channel-kind ↔ channel-id agreement at
    binding time. Each adapter answers exactly this shape.
    """

    channel_kind: ChannelKind
    channel_id: str
    trust_tiers: frozenset[TrustTier]

    async def send(self, message: NotificationMessage) -> DeliveryReceipt: ...


@runtime_checkable
class HilEscalationSink(Protocol):
    """Fail-safe sink invoked when every channel for a route is down.

    The router calls this after exhausting the matrix (primary + every
    fallback) so a message never gets silently dropped. Concrete
    implementations enqueue into the human-in-the-loop queue and emit a
    kill-switch-adjacent A2 alert (see
    ``channels-and-notifications.md § 8``). Kept as a Protocol so a fork
    can wire its own queue backend.
    """

    async def escalate(self, message: NotificationMessage, reason: str) -> None: ...


__all__ = [
    "ChannelDeliveryError",
    "ChannelKind",
    "ChannelUnavailableError",
    "DeliveryReceipt",
    "HilEscalationSink",
    "Link",
    "NotificationChannel",
    "NotificationMessage",
    "Severity",
    "TrustTier",
]
