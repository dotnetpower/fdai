"""Slack incoming-webhook adapter (Block Kit body).

Only the ``chat:write`` equivalent (webhook posts) is used - the
adapter never authorizes decisions. The webhook URL is a per-channel
secret loaded via the composition root, same pattern as the Teams
adapter.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Final

import httpx

from fdai.shared.providers.notifications.base import (
    ChannelAmbiguousError,
    ChannelDeliveryError,
    ChannelKind,
    ChannelUnavailableError,
    DeliveryReceipt,
    NotificationMessage,
    Severity,
    TrustTier,
    require_channel_id,
)
from fdai.shared.providers.notifications.presentation import (
    NotificationPresentationEnvelope,
    RenderedNotificationPayload,
    render_presentation,
)

from ._rendering import truncate_with_marker

SLACK_CHAT_POST_MESSAGE_URL: Final[str] = "https://slack.com/api/chat.postMessage"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
_MAX_HEADER_CHARS: Final[int] = 150
_MAX_SECTION_CHARS: Final[int] = 3000
_MAX_FIELDS_PER_SECTION: Final[int] = 10
_MAX_PAYLOAD_BYTES: Final[int] = 40 * 1024
_CONTENT_TYPE: Final[str] = "application/json"
_SLACK_CHANNEL_ID_RE: Final = re.compile(r"^[CDG][A-Z0-9]{8,14}$")
_SLACK_TS_RE: Final = re.compile(r"^[0-9]{1,16}\.[0-9]{1,12}$")
_SEVERITY_COLORS: Final[dict[Severity, str]] = {
    Severity.INFO: "#36C5F0",
    Severity.WARN: "#ECB22E",
    Severity.ERROR: "#E01E5A",
    Severity.CRITICAL: "#E01E5A",
}


@dataclass(frozen=True, slots=True)
class SlackWebhookConfig:
    channel_id: str
    webhook_url: str
    trust_tiers: frozenset[TrustTier]
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    slack_channel_id: str | None = None
    bot_token: str | None = field(default=None, repr=False)


class SlackWebhookChannel:
    channel_kind: Final = ChannelKind.SLACK

    def __init__(self, *, config: SlackWebhookConfig, http_client: httpx.AsyncClient) -> None:
        require_channel_id(config.channel_id)
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not config.webhook_url:
            raise ValueError("webhook_url MUST NOT be empty")
        if not config.webhook_url.startswith("https://"):
            raise ValueError("webhook_url MUST use https:// scheme")
        if (config.slack_channel_id is None) != (config.bot_token is None):
            raise ValueError("slack_channel_id and bot_token MUST be configured together")
        if config.slack_channel_id is not None and config.bot_token is not None:
            if config.webhook_url != SLACK_CHAT_POST_MESSAGE_URL:
                raise ValueError(
                    "Slack Web API delivery requires the fixed HTTPS chat.postMessage URL"
                )
            if _SLACK_CHANNEL_ID_RE.fullmatch(config.slack_channel_id) is None:
                raise ValueError("slack_channel_id MUST be a bounded Slack channel identifier")
            if (
                not config.bot_token
                or config.bot_token != config.bot_token.strip()
                or any(ch.isspace() for ch in config.bot_token)
            ):
                raise ValueError("bot_token MUST be a protected non-empty credential")
        self._config: Final = config
        self._http: Final = http_client

    @property
    def channel_id(self) -> str:
        return self._config.channel_id

    @property
    def trust_tiers(self) -> frozenset[TrustTier]:
        return self._config.trust_tiers

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        payload = render_slack_payload(render_presentation(message, channel_id=self.channel_id))
        headers = {"Content-Type": payload.content_type}
        body = payload.body
        web_api_mode = (
            self._config.slack_channel_id is not None and self._config.bot_token is not None
        )
        if web_api_mode:
            body_obj = json.loads(payload.body.decode("utf-8"))
            body_obj["channel"] = self._config.slack_channel_id
            body = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(body) > _MAX_PAYLOAD_BYTES:
                raise ChannelDeliveryError(f"Slack payload exceeds {_MAX_PAYLOAD_BYTES} bytes")
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self._config.bot_token}",
            }
        try:
            response = await self._http.post(
                self._config.webhook_url,
                content=body,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise ChannelUnavailableError(
                f"Slack webhook transport error: {type(exc).__name__}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ChannelAmbiguousError(
                f"Slack webhook acknowledgement was not observed: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            raise ChannelDeliveryError(f"Slack webhook returned HTTP {response.status_code}")
        provider_message_id = message.correlation_id
        if web_api_mode:
            try:
                ack = response.json()
            except ValueError as exc:
                raise ChannelAmbiguousError(
                    "Slack chat.postMessage acknowledgement was not valid JSON"
                ) from exc
            if not isinstance(ack, dict) or ack.get("ok") is not True:
                raise ChannelDeliveryError("Slack chat.postMessage rejected the request")
            ts = ack.get("ts")
            if not isinstance(ts, str) or _SLACK_TS_RE.fullmatch(ts) is None:
                raise ChannelAmbiguousError(
                    "Slack chat.postMessage acknowledgement is missing a valid message ts"
                )
            provider_message_id = ts
        return DeliveryReceipt(
            channel_kind=ChannelKind.SLACK,
            channel_id=self._config.channel_id,
            delivered=False,
            accepted=True,
            provider_message_id=provider_message_id,
        )


def render_slack_payload(
    envelope: NotificationPresentationEnvelope,
) -> RenderedNotificationPayload:
    """Render a bounded envelope into an immutable Slack Block Kit payload."""

    encoded = json.dumps(
        _block_kit(envelope),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise ChannelDeliveryError(f"Slack payload exceeds {_MAX_PAYLOAD_BYTES} bytes")
    return RenderedNotificationPayload(content_type=_CONTENT_TYPE, body=encoded)


def _block_kit(message: NotificationPresentationEnvelope) -> dict[str, object]:
    """Render the message into a Slack Block Kit payload.

    Emoji prefix on the header block preserves severity semantics
    without leaking secret data.
    """
    header_text, title_truncated = truncate_with_marker(
        f"{_severity_emoji(message.severity)} {message.title}",
        limit=_MAX_HEADER_CHARS,
    )
    body_text, body_truncated = truncate_with_marker(
        message.body_markdown,
        limit=_MAX_SECTION_CHARS,
    )
    blocks: list[dict[str, object]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": body_text},
        },
    ]
    fields: list[dict[str, str]] = [
        *(
            [
                {
                    "type": "mrkdwn",
                    "text": f"*correlation_id*\n{_escape_slack_text(message.correlation_id)}",
                }
            ]
            if message.correlation_id
            else []
        ),
        *(
            [
                {
                    "type": "mrkdwn",
                    "text": f"*audit_id*\n{_escape_slack_text(message.audit_id)}",
                }
            ]
            if message.audit_id
            else []
        ),
        *(
            {
                "type": "mrkdwn",
                "text": f"*{_escape_slack_text(key)}*\n{_escape_slack_text(value)}",
            }
            for key, value in sorted(message.metadata.items())
        ),
    ]
    for start in range(0, len(fields), _MAX_FIELDS_PER_SECTION):
        blocks.append(
            {
                "type": "section",
                "fields": fields[start : start + _MAX_FIELDS_PER_SECTION],
            }
        )
    if message.links:
        links = "\n".join(
            f"<{link.url.replace('|', '%7C')}|{_escape_slack_text(link.label)}>"
            for link in message.links
        )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": links},
            }
        )
    truncated_fields = [
        name
        for name, truncated in (("title", title_truncated), ("body", body_truncated))
        if truncated
    ]
    if truncated_fields:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"rendering: truncated {', '.join(truncated_fields)}",
                    }
                ],
            }
        )
    return {
        "text": header_text,
        "attachments": [
            {
                "color": _SEVERITY_COLORS[message.severity],
                "blocks": blocks,
            }
        ],
    }


def _escape_slack_text(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "&#124;")
    )


def _severity_emoji(severity: Severity) -> str:
    return {
        Severity.INFO: ":information_source:",
        Severity.WARN: ":warning:",
        Severity.ERROR: ":rotating_light:",
        Severity.CRITICAL: ":rotating_light:",
    }[severity]


__all__ = [
    "SLACK_CHAT_POST_MESSAGE_URL",
    "SlackWebhookChannel",
    "SlackWebhookConfig",
    "render_slack_payload",
]
