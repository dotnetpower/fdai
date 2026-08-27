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
)

from ._http import truncate

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
_MAX_PAYLOAD_BYTES: Final[int] = 28 * 1024


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
        payload = _adaptive_card(message)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_PAYLOAD_BYTES:
            raise ChannelDeliveryError(f"Teams Workflow payload exceeds {_MAX_PAYLOAD_BYTES} bytes")
        headers = {"Content-Type": "application/json"}
        if self._config.auth_mode is TeamsWorkflowAuthMode.WORKLOAD_IDENTITY:
            token_provider = self._token_provider
            if token_provider is None:
                raise RuntimeError("Teams Workflow token provider is unavailable")
            token = (await token_provider()).strip()
            if not token:
                raise ChannelDeliveryError("Teams Workflow token provider returned an empty token")
            headers["Authorization"] = f"Bearer {token}"

        response = await self._post_with_retry(encoded, headers)
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
                    "Teams Workflow request failed with "
                    f"HTTP {response.status_code}: {truncate(response.text or '')!r}"
                )
            delay = min(
                self._config.max_backoff_seconds,
                self._config.backoff_seconds * (2 ** (attempt - 1)),
            )
            if delay:
                await self._sleep(delay)
        raise RuntimeError("Teams Workflow retry loop exited without a response")


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
                "contentUrl": None,
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


__all__ = [
    "TeamsWebhookChannel",
    "TeamsWebhookConfig",
    "TeamsWorkflowAuthMode",
]
