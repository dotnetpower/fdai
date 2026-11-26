"""Pure Direct Line activity renderer shared by rehearsal and governed delivery.

Both the shadow channel and :class:`~.direct_line.DirectLineNotificationChannel`
call :func:`render_direct_line_payload`, so a rehearsal record contains the exact
activity a governed send would post. The renderer never sees an endpoint,
conversation id, or credential.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Final
from urllib.parse import quote

from fdai.shared.providers.notifications.base import ChannelDeliveryError, Severity
from fdai.shared.providers.notifications.presentation import (
    NotificationPresentationEnvelope,
    RenderedNotificationPayload,
)

from ._rendering import truncate_with_marker

DIRECT_LINE_DEFAULT_SENDER_ID: Final[str] = "fdai-notifications"
_SENDER_NAME: Final[str] = "FDAI"
_MAX_PAYLOAD_BYTES: Final[int] = 48 * 1024
_MAX_TITLE_CHARS: Final[int] = 250
_MAX_BODY_CHARS: Final[int] = 3000
_CONTENT_TYPE: Final[str] = "application/json"
_SENDER_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MARKDOWN_CONTROL: Final = re.compile(r"([\\`*_\[\]<>|~])")
_LINK_TARGET_SAFE: Final[str] = ":/?#[]@!$&'*+,;=%-._~"
_SEVERITY_LABELS: Final[dict[Severity, str]] = {
    Severity.INFO: "INFORMATION",
    Severity.WARN: "ATTENTION",
    Severity.ERROR: "CRITICAL",
    Severity.CRITICAL: "CRITICAL",
}


def require_direct_line_sender_id(sender_id: str) -> str:
    """Return one bounded ASCII activity sender id or raise :class:`ValueError`."""

    if _SENDER_ID.fullmatch(sender_id) is None:
        raise ValueError("Direct Line sender_id MUST be a bounded ASCII identifier")
    return sender_id


def render_direct_line_payload(
    envelope: NotificationPresentationEnvelope,
    *,
    sender_id: str = DIRECT_LINE_DEFAULT_SENDER_ID,
) -> RenderedNotificationPayload:
    """Render a bounded envelope into an immutable Direct Line message activity.

    The activity carries readable Markdown text and a ``channelData.fdai``
    record with canonical ids plus a stable ``idempotency_key`` that the relay
    bot MUST use to suppress a duplicate post after a retry or replay. It never
    carries attachments, suggested actions, or approval or command controls.
    Raises :class:`ChannelDeliveryError` rather than truncating mandatory
    content when the serialized activity exceeds the bounded payload size.
    """

    require_direct_line_sender_id(sender_id)
    encoded = json.dumps(
        _activity(envelope, sender_id=sender_id),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise ChannelDeliveryError(f"Direct Line payload exceeds {_MAX_PAYLOAD_BYTES} bytes")
    return RenderedNotificationPayload(content_type=_CONTENT_TYPE, body=encoded)


def direct_line_idempotency_key(envelope: NotificationPresentationEnvelope) -> str:
    """Return the stable per-channel key shared by rehearsal and governed sends.

    Uses the same ``channel_id + correlation_id + audit_id + category``
    identity as the shadow record id, so a replayed send reproduces the key.
    """

    material = "\x1f".join(
        (envelope.channel_id, envelope.correlation_id, envelope.audit_id or "", envelope.category)
    ).encode()
    return hashlib.sha256(material).hexdigest()


def _activity(message: NotificationPresentationEnvelope, *, sender_id: str) -> dict[str, object]:
    title, title_truncated = truncate_with_marker(message.title, limit=_MAX_TITLE_CHARS)
    body, body_truncated = truncate_with_marker(message.body_markdown, limit=_MAX_BODY_CHARS)
    truncated = [
        name for name, flag in (("title", title_truncated), ("body", body_truncated)) if flag
    ]
    facts: list[tuple[str, str]] = [("correlation_id", message.correlation_id)]
    if message.audit_id:
        facts.append(("audit_id", message.audit_id))
    metadata = sorted(message.metadata.items())
    facts.extend(metadata)
    if truncated:
        facts.append(("rendering", f"truncated {', '.join(truncated)}"))
    lines = [f"**{_SEVERITY_LABELS[message.severity]}** {_inline(title)}", "", body, ""]
    lines.extend(f"- {_inline(key)}: {_inline(value)}" for key, value in facts)
    if message.links:
        lines.append("")
        lines.extend(f"[{_inline(link.label)}]({_link_target(link.url)})" for link in message.links)
    return {
        "type": "message",
        "from": {"id": sender_id, "name": _SENDER_NAME},
        "textFormat": "markdown",
        "text": "\n".join(lines),
        "channelData": {
            "fdai": {
                "schema_version": 1,
                "read_only": True,
                "idempotency_key": direct_line_idempotency_key(message),
                "channel_id": message.channel_id,
                "category": message.category,
                "trust_tier": message.trust_tier.value,
                "severity": message.severity.value,
                "correlation_id": message.correlation_id,
                "audit_id": message.audit_id,
                "title": title,
                "metadata": dict(metadata),
                "links": [{"label": link.label, "url": link.url} for link in message.links],
            }
        },
    }


def _inline(value: str) -> str:
    """Escape one inline field so it cannot open a link, image, or new block."""

    single_line = " ".join(value.splitlines())
    return _MARKDOWN_CONTROL.sub(r"\\\1", single_line)


def _link_target(url: str) -> str:
    """Percent-encode characters that would end a Markdown link target early."""

    return quote(url, safe=_LINK_TARGET_SAFE)


__all__ = [
    "DIRECT_LINE_DEFAULT_SENDER_ID",
    "direct_line_idempotency_key",
    "render_direct_line_payload",
    "require_direct_line_sender_id",
]
