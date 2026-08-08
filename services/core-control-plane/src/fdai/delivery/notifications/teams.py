"""Microsoft Teams incoming-webhook adapter (Adaptive Card body).

The webhook URL is a per-channel secret loaded through the
:class:`~fdai.shared.providers.secret_provider.SecretProvider` at
composition time; this adapter never touches env vars directly.
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
class TeamsWebhookConfig:
    """Config a fork supplies at composition time."""

    channel_id: str
    webhook_url: str
    trust_tiers: frozenset[TrustTier]
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


class TeamsWebhookChannel:
    """POSTs an Adaptive Card payload to a Teams incoming-webhook URL."""

    channel_kind: Final = ChannelKind.TEAMS

    def __init__(self, *, config: TeamsWebhookConfig, http_client: httpx.AsyncClient) -> None:
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
        payload = _adaptive_card(message)
        await post_json(
            client=self._http,
            url=self._config.webhook_url,
            payload=payload,
            timeout_seconds=self._config.timeout_seconds,
        )
        return DeliveryReceipt(
            channel_kind=ChannelKind.TEAMS,
            channel_id=self._config.channel_id,
            delivered=True,
            provider_message_id=message.correlation_id,
        )


def _adaptive_card(message: NotificationMessage) -> dict[str, object]:
    """Wrap ``message`` in a minimal Adaptive Card envelope.

    Kept intentionally small - Teams accepts the ``TextBlock`` +
    ``FactSet`` + ``ActionSet`` primitives universally, so a fork can
    override this without changing the adapter.
    """
    body: list[dict[str, object]] = [
        {
            "type": "TextBlock",
            "size": "Medium",
            "weight": "Bolder",
            "text": message.title,
            "color": _severity_color(message.severity),
        },
        {
            "type": "TextBlock",
            "wrap": True,
            "text": message.body_markdown,
        },
    ]
    if message.audit_id or message.correlation_id:
        body.append(
            {
                "type": "FactSet",
                "facts": [
                    {"title": "correlation_id", "value": message.correlation_id},
                    *(
                        [{"title": "audit_id", "value": message.audit_id}]
                        if message.audit_id
                        else []
                    ),
                ],
            }
        )
    actions: list[dict[str, object]] = [
        {"type": "Action.OpenUrl", "title": link.label, "url": link.url} for link in message.links
    ]
    card: dict[str, object] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }
        ],
    }


def _severity_color(severity: Severity) -> str:
    return {
        Severity.INFO: "Default",
        Severity.WARN: "Warning",
        Severity.ERROR: "Attention",
        Severity.CRITICAL: "Attention",
    }[severity]


__all__ = ["TeamsWebhookChannel", "TeamsWebhookConfig"]
