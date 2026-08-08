"""Slack incoming-webhook adapter (Block Kit body).

Only the ``chat:write`` equivalent (webhook posts) is used - the
adapter never authorizes decisions. The webhook URL is a per-channel
secret loaded via the composition root, same pattern as the Teams
adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import httpx

from fdai.shared.providers.notifications.base import (
    ChannelKind,
    DeliveryReceipt,
    NotificationMessage,
    Severity,
    TrustTier,
)

from ._http import post_json

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0


@dataclass(frozen=True, slots=True)
class SlackWebhookConfig:
    channel_id: str
    webhook_url: str
    trust_tiers: frozenset[TrustTier]
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


class SlackWebhookChannel:
    channel_kind: Final = ChannelKind.SLACK

    def __init__(self, *, config: SlackWebhookConfig, http_client: httpx.AsyncClient) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not config.webhook_url:
            raise ValueError("webhook_url MUST NOT be empty")
        if not config.webhook_url.startswith("https://"):
            raise ValueError("webhook_url MUST use https:// scheme")
        self._config: Final = config
        self._http: Final = http_client

    @property
    def channel_id(self) -> str:
        return self._config.channel_id

    @property
    def trust_tiers(self) -> frozenset[TrustTier]:
        return self._config.trust_tiers

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        payload = _block_kit(message)
        await post_json(
            client=self._http,
            url=self._config.webhook_url,
            payload=payload,
            timeout_seconds=self._config.timeout_seconds,
            ok_statuses=(200,),
        )
        return DeliveryReceipt(
            channel_kind=ChannelKind.SLACK,
            channel_id=self._config.channel_id,
            delivered=True,
            provider_message_id=message.correlation_id,
        )


def _block_kit(message: NotificationMessage) -> dict[str, object]:
    """Render the message into a Slack Block Kit payload.

    Emoji prefix on the header block preserves severity semantics
    without leaking secret data.
    """
    header_text = f"{_severity_emoji(message.severity)} {message.title}"
    blocks: list[dict[str, object]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text[:150], "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message.body_markdown},
        },
    ]
    if message.correlation_id or message.audit_id:
        fields: list[dict[str, str]] = [
            {"type": "mrkdwn", "text": f"*correlation_id*\n{message.correlation_id}"},
        ]
        if message.audit_id:
            fields.append({"type": "mrkdwn", "text": f"*audit_id*\n{message.audit_id}"})
        blocks.append({"type": "section", "fields": fields})
    if message.links:
        elements: list[dict[str, object]] = []
        for link in message.links:
            elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": link.label},
                    "url": link.url,
                }
            )
        blocks.append({"type": "actions", "elements": elements})
    return {
        "text": message.title,
        "blocks": blocks,
    }


def _severity_emoji(severity: Severity) -> str:
    return {
        Severity.INFO: ":information_source:",
        Severity.WARN: ":warning:",
        Severity.ERROR: ":rotating_light:",
        Severity.CRITICAL: ":rotating_light:",
    }[severity]


__all__ = ["SlackWebhookChannel", "SlackWebhookConfig"]
