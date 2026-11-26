"""Microsoft Teams Workflows webhook adapter (Adaptive Card body).

The webhook URL is a per-channel secret loaded through the
:class:`~fdai.shared.providers.secret_provider.SecretProvider` at
composition time; this adapter never touches env vars directly.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
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

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
_MAX_PAYLOAD_BYTES: Final[int] = 28 * 1024
_MAX_TITLE_CHARS: Final[int] = 250
_MAX_BODY_CHARS: Final[int] = 3000
_CONTENT_TYPE: Final[str] = "application/json"
_SEVERITY_PRESENTATION: Final[dict[Severity, tuple[str, str]]] = {
    Severity.INFO: ("INFORMATION", "Accent"),
    Severity.WARN: ("ATTENTION", "Warning"),
    Severity.ERROR: ("CRITICAL", "Attention"),
    Severity.CRITICAL: ("CRITICAL", "Attention"),
}


class TeamsWorkflowAuthMode(StrEnum):
    ANYONE = "anyone"
    WORKLOAD_IDENTITY = "workload_identity"


@dataclass(frozen=True, slots=True)
class TeamsWebhookConfig:
    """Config a fork supplies at composition time."""

    channel_id: str
    webhook_url: str
    trust_tiers: frozenset[TrustTier]
    auth_mode: TeamsWorkflowAuthMode = TeamsWorkflowAuthMode.ANYONE
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = 3
    backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0


class TeamsWebhookChannel:
    """POST an Adaptive Card to a Teams Workflows trigger."""

    channel_kind: Final = ChannelKind.TEAMS

    def __init__(
        self,
        *,
        config: TeamsWebhookConfig,
        http_client: httpx.AsyncClient,
        token_provider: Callable[[], Awaitable[str]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        require_channel_id(config.channel_id)
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not config.webhook_url:
            raise ValueError("webhook_url MUST NOT be empty")
        if not config.webhook_url.startswith("https://"):
            raise ValueError("webhook_url MUST use https:// scheme")
        if config.max_attempts < 1:
            raise ValueError("max_attempts MUST be >= 1")
        if config.backoff_seconds < 0 or config.max_backoff_seconds < 0:
            raise ValueError("Teams Workflow backoff bounds MUST be >= 0")
        if config.auth_mode is TeamsWorkflowAuthMode.WORKLOAD_IDENTITY and token_provider is None:
            raise ValueError("workload_identity auth requires a token_provider")
        if config.auth_mode is TeamsWorkflowAuthMode.ANYONE and token_provider is not None:
            raise ValueError("anyone auth MUST NOT configure a token_provider")
        self._config: Final = config
        self._http: Final = http_client
        self._token_provider: Final = token_provider
        self._sleep: Final = sleep

    @property
    def channel_id(self) -> str:
        return self._config.channel_id

    @property
    def trust_tiers(self) -> frozenset[TrustTier]:
        return self._config.trust_tiers

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        payload = render_teams_payload(render_presentation(message, channel_id=self.channel_id))
        headers = {"Content-Type": payload.content_type}
        if self._config.auth_mode is TeamsWorkflowAuthMode.WORKLOAD_IDENTITY:
            token_provider = self._token_provider
            if token_provider is None:
                raise RuntimeError("Teams Workflow token provider is unavailable")
            token = (await token_provider()).strip()
            if not token:
                raise ChannelDeliveryError("Teams Workflow token provider returned an empty token")
            headers["Authorization"] = f"Bearer {token}"

        response = await self._post_with_retry(payload.body, headers)
        provider_message_id = response.headers.get("x-ms-workflow-run-id") or message.correlation_id
        return DeliveryReceipt(
            channel_kind=ChannelKind.TEAMS,
            channel_id=self._config.channel_id,
            delivered=False,
            accepted=True,
            provider_message_id=provider_message_id,
        )

    async def _post_with_retry(
        self,
        payload: bytes,
        headers: dict[str, str],
    ) -> httpx.Response:
        for attempt in range(1, self._config.max_attempts + 1):
            try:
                response = await self._http.post(
                    self._config.webhook_url,
                    content=payload,
                    headers=headers,
                    timeout=self._config.timeout_seconds,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                raise ChannelUnavailableError(
                    f"Teams Workflow connection failed: {type(exc).__name__}"
                ) from exc
            except httpx.HTTPError as exc:
                raise ChannelAmbiguousError(
                    f"Teams Workflow acknowledgement was not observed: {type(exc).__name__}"
                ) from exc

            if response.status_code in {200, 201, 202, 204}:
                return response
            if response.status_code != 429 or attempt == self._config.max_attempts:
                raise ChannelDeliveryError(
                    f"Teams Workflow request failed with HTTP {response.status_code}"
                )
            delay = min(
                self._config.max_backoff_seconds,
                self._config.backoff_seconds * (2 ** (attempt - 1)),
            )
            if delay:
                await self._sleep(delay)
        raise RuntimeError("Teams Workflow retry loop exited without a response")


def render_teams_payload(
    envelope: NotificationPresentationEnvelope,
) -> RenderedNotificationPayload:
    """Render a bounded envelope into an immutable Teams Workflows payload."""

    encoded = json.dumps(
        _adaptive_card(envelope),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise ChannelDeliveryError(f"Teams Workflow payload exceeds {_MAX_PAYLOAD_BYTES} bytes")
    return RenderedNotificationPayload(content_type=_CONTENT_TYPE, body=encoded)


def _adaptive_card(message: NotificationPresentationEnvelope) -> dict[str, object]:
    """Wrap ``message`` in an accessible Adaptive Card envelope.

    The card uses only the conservative ``TextBlock``, ``FactSet``, and
    ``Action.OpenUrl`` primitives supported by Teams Workflows.
    """
    title, title_truncated = truncate_with_marker(message.title, limit=_MAX_TITLE_CHARS)
    body_text, body_truncated = truncate_with_marker(
        message.body_markdown,
        limit=_MAX_BODY_CHARS,
    )
    severity_label, severity_color = _SEVERITY_PRESENTATION[message.severity]
    body: list[dict[str, object]] = [
        {
            "type": "TextBlock",
            "text": severity_label,
            "weight": "Bolder",
            "size": "Small",
            "color": severity_color,
            "horizontalAlignment": "Center",
            "spacing": "None",
        },
        {
            "type": "TextBlock",
            "text": title,
            "weight": "Bolder",
            "size": "ExtraLarge",
            "wrap": True,
            "horizontalAlignment": "Center",
            "spacing": "Small",
        },
        {
            "type": "TextBlock",
            "wrap": True,
            "text": body_text,
            "isSubtle": True,
            "size": "Medium",
            "horizontalAlignment": "Center",
            "spacing": "Medium",
        },
    ]
    facts: list[dict[str, str]] = [
        *(
            [{"title": "correlation_id", "value": message.correlation_id}]
            if message.correlation_id
            else []
        ),
        *([{"title": "audit_id", "value": message.audit_id}] if message.audit_id else []),
        *({"title": key, "value": value} for key, value in sorted(message.metadata.items())),
    ]
    truncated_fields = [
        name
        for name, truncated in (("title", title_truncated), ("body", body_truncated))
        if truncated
    ]
    if truncated_fields:
        facts.append({"title": "rendering", "value": f"truncated: {', '.join(truncated_fields)}"})
    if facts:
        body.append(
            {
                "type": "FactSet",
                "separator": True,
                "spacing": "Medium",
                "facts": facts,
            }
        )
    actions: list[dict[str, object]] = [
        {"type": "Action.OpenUrl", "title": link.label, "url": link.url} for link in message.links
    ]
    card: dict[str, object] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "fallbackText": f"{title}: {body_text}",
        "speak": f"{title}: {body_text}",
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


__all__ = [
    "TeamsWebhookChannel",
    "TeamsWebhookConfig",
    "TeamsWorkflowAuthMode",
    "render_teams_payload",
]
