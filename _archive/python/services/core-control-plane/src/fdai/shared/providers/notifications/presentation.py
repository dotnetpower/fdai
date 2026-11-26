"""Provider-neutral pre-render presentation contract for A2/A4 notifications.

Every :class:`~fdai.shared.providers.notifications.NotificationChannel`
adapter that renders a message into vendor markup - including
:class:`fdai.core.notifications.shadow.ShadowNotificationChannel` - MAY pass
its message through :func:`render_presentation` before any vendor formatting
or network call; the shadow channel MUST. The boundary fails closed:
secret-like content, content that exceeds a bounded size, an unsafe link
scheme, and unsupported interactive content all raise
:class:`PresentationRejectedError` rather than truncating or silently
stripping data, matching "Redaction is the sender's job" (design principle 5
in `docs/roadmap/interfaces/channels-and-notifications.md § 1`) and "A2/A4
messages never contain approval buttons or executable links" (§ 3 of the
same document).

The result, :class:`NotificationPresentationEnvelope`, is immutable and
carries only the bounded, already-validated fields a renderer needs.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from .base import ChannelDeliveryError, Link, NotificationMessage, Severity, TrustTier

INTERACTIVE_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {"actions", "buttons", "action_buttons", "interactive", "quick_replies", "components"}
)
"""Metadata keys that would carry interactive content A2/A4 MUST NOT render.

A2/A4 messages carry links only - never inline action buttons - so every
actionable path re-enters through `fdai-api` where it can be authenticated.
A message whose metadata names one of these keys is a defect at the call
site, not a render-time truncation decision, so it is rejected outright.
Every member is already lower-case; :func:`render_presentation` compares a
message's metadata keys with :meth:`str.casefold` so ``"Actions"`` or
``"ACTIONS"`` is rejected exactly like ``"actions"`` - the boundary MUST NOT
depend on the caller's key casing.
"""

_SECRET_PATTERNS: Final = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~-]{12,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|access[_-]?token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)[?&](?:sig|se|sp|sv|token)=[^&\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bgh[opusr]_[a-z0-9]{20,}\b"),
    re.compile(r"(?i)\bxox[baprs]-[a-z0-9-]{10,}\b"),
)
"""Bounded, high-signal secret shapes, scanned without ever echoing a match.

Mirrors the fail-closed idiom in :mod:`fdai.core.trajectory.scanning` but is
defined locally so `shared/providers/` never depends on `core/` (the
dependency direction the composition root's boundary checks enforce).
"""


class PresentationRejectedError(ChannelDeliveryError):
    """Raised when a message fails the pre-render presentation boundary.

    A rejected message is never partially rendered. The caller (router or
    adapter) receives this exactly like any other
    :class:`~fdai.shared.providers.notifications.ChannelDeliveryError` and
    proceeds to the next configured fallback channel or bounded retry.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"notification presentation rejected: {reason}")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class PresentationLimits:
    """Bounds enforced before any provider call.

    Defaults are conservative and provider-neutral; a concrete adapter MAY
    apply a stricter vendor ceiling on top of these, never a looser one.
    """

    max_title_chars: int = 300
    max_body_chars: int = 4000
    max_links: int = 5
    max_link_label_chars: int = 80
    max_link_url_chars: int = 2000
    max_metadata_entries: int = 16
    max_metadata_key_chars: int = 64
    max_metadata_value_chars: int = 200

    def __post_init__(self) -> None:
        values = (
            self.max_title_chars,
            self.max_body_chars,
            self.max_links,
            self.max_link_label_chars,
            self.max_link_url_chars,
            self.max_metadata_entries,
            self.max_metadata_key_chars,
            self.max_metadata_value_chars,
        )
        if any(value < 1 for value in values):
            raise ValueError("presentation limits MUST be positive")


@dataclass(frozen=True, slots=True)
class NotificationPresentationEnvelope:
    """Immutable, pre-validated boundary artifact a renderer may format.

    Construct only via :func:`render_presentation`; the presence of an
    instance is itself evidence the redaction, bound, and interactive-content
    checks already passed for exactly this content. ``metadata`` is a
    :class:`~types.MappingProxyType` view, not a plain ``dict`` - the frozen
    dataclass alone only stops a caller from rebinding the attribute, so
    without this the "immutable" claim would not actually hold for a mutable
    mapping reachable through it.
    """

    channel_id: str
    category: str
    trust_tier: TrustTier
    correlation_id: str
    title: str
    body_markdown: str
    severity: Severity
    links: tuple[Link, ...]
    metadata: Mapping[str, str]
    audit_id: str | None = None


@dataclass(frozen=True, slots=True)
class RenderedNotificationPayload:
    """Immutable provider payload produced by a pure presentation renderer."""

    content_type: str
    body: bytes

    def __post_init__(self) -> None:
        if not self.content_type:
            raise ValueError("rendered notification content_type MUST be non-empty")
        if not self.body:
            raise ValueError("rendered notification body MUST be non-empty")


NotificationPayloadRenderer = Callable[
    [NotificationPresentationEnvelope],
    RenderedNotificationPayload,
]
"""Pure provider renderer used identically by shadow and enforce channels."""


def render_presentation(
    message: NotificationMessage,
    *,
    channel_id: str,
    limits: PresentationLimits | None = None,
) -> NotificationPresentationEnvelope:
    """Validate ``message`` at the presentation boundary for ``channel_id``.

    Fails closed with :class:`PresentationRejectedError` before any vendor
    formatting when the message declares unsupported interactive content,
    contains a high-signal secret-like pattern, or exceeds a bound in
    ``limits``. Never truncates or silently drops content to make it fit -
    "If mandatory content alone cannot fit, rendering fails closed before a
    provider call" (`channels-and-notifications.md § 4.2`). Both metadata
    keys and values are bounded and scanned for secret-like content - an
    unbounded key would let a caller smuggle an oversized or secret-bearing
    payload past a check that only looked at values.
    """
    bounds = limits if limits is not None else PresentationLimits()

    interactive = sorted(
        key for key in message.metadata if key.casefold() in INTERACTIVE_METADATA_KEYS
    )
    if interactive:
        raise PresentationRejectedError(
            f"unsupported interactive content in metadata keys {interactive!r}"
        )

    if len(message.title) > bounds.max_title_chars:
        raise PresentationRejectedError("title exceeds the bounded presentation limit")
    if len(message.body_markdown) > bounds.max_body_chars:
        raise PresentationRejectedError("body exceeds the bounded presentation limit")
    if len(message.links) > bounds.max_links:
        raise PresentationRejectedError("link count exceeds the bounded presentation limit")
    for link in message.links:
        if len(link.label) > bounds.max_link_label_chars:
            raise PresentationRejectedError("link label exceeds the bounded presentation limit")
        if len(link.url) > bounds.max_link_url_chars:
            raise PresentationRejectedError("link url exceeds the bounded presentation limit")
        if not link.url.casefold().startswith("https://"):
            raise PresentationRejectedError(
                "link url MUST be an absolute https link - never an executable scheme"
            )
    if len(message.metadata) > bounds.max_metadata_entries:
        raise PresentationRejectedError(
            "metadata entry count exceeds the bounded presentation limit"
        )
    for key in message.metadata:
        if len(key) > bounds.max_metadata_key_chars:
            raise PresentationRejectedError("metadata key exceeds the bounded presentation limit")
    for value in message.metadata.values():
        if len(value) > bounds.max_metadata_value_chars:
            raise PresentationRejectedError("metadata value exceeds the bounded presentation limit")

    _reject_secret_like(message)

    return NotificationPresentationEnvelope(
        channel_id=channel_id,
        category=message.category,
        trust_tier=message.trust_tier,
        correlation_id=message.correlation_id,
        title=message.title,
        body_markdown=message.body_markdown,
        severity=message.severity,
        links=message.links,
        metadata=MappingProxyType(dict(message.metadata)),
        audit_id=message.audit_id,
    )


def _reject_secret_like(message: NotificationMessage) -> None:
    haystacks = (
        message.title,
        message.body_markdown,
        *(link.label for link in message.links),
        *(link.url for link in message.links),
        *message.metadata.keys(),
        *message.metadata.values(),
    )
    for haystack in haystacks:
        if any(pattern.search(haystack) for pattern in _SECRET_PATTERNS):
            raise PresentationRejectedError("secret-like content detected")


__all__ = [
    "INTERACTIVE_METADATA_KEYS",
    "NotificationPayloadRenderer",
    "NotificationPresentationEnvelope",
    "PresentationLimits",
    "PresentationRejectedError",
    "RenderedNotificationPayload",
    "render_presentation",
]
