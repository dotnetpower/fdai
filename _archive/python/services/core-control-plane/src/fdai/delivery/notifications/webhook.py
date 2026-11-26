"""Generic outbound-webhook adapter.

HMAC-SHA256 signature over ``timestamp + "." + body`` (canonical
Slack/GitHub shape). Timestamp is monotonic (UNIX seconds); receivers
verify the signature and MUST reject requests older than a small skew.

The secret is handed in at construction time - the composition root
loads it via the
:class:`~fdai.shared.providers.secret_provider.SecretProvider` seam
so this module never touches env vars or vaults.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

import httpx

from fdai.shared.providers.notifications.base import (
    ChannelDeliveryError,
    ChannelKind,
    ChannelUnavailableError,
    DeliveryReceipt,
    NotificationMessage,
    TrustTier,
)

from ._http import truncate

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0


@dataclass(frozen=True, slots=True)
class GenericWebhookConfig:
    channel_id: str
    url: str
    hmac_secret: str
    """Shared secret used to sign every request. Never logged, never
    echoed. Provided by :class:`SecretProvider` at composition time."""

    trust_tiers: frozenset[TrustTier] = frozenset({TrustTier.A2_OPERATIONAL_ALERT})
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


class GenericWebhookChannel:
    """POSTs a signed JSON envelope to an arbitrary webhook URL."""

    channel_kind: Final = ChannelKind.WEBHOOK

    def __init__(self, *, config: GenericWebhookConfig, http_client: httpx.AsyncClient) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not config.url:
            raise ValueError("url MUST NOT be empty")
        if not config.url.startswith("https://"):
            # The HMAC signature protects the body, not the transport;
            # http:// still leaks the URL, method, and headers to any
            # on-path observer. Refuse construction so a fork cannot
            # accidentally sign over cleartext.
            raise ValueError("url MUST use https:// scheme")
        if not config.hmac_secret:
            raise ValueError("hmac_secret MUST NOT be empty")
        if TrustTier.A1_HIL_APPROVAL in config.trust_tiers:
            raise ValueError("generic webhook MUST NOT carry A1 approvals")
        self._config: Final = config
        self._http: Final = http_client

    @property
    def channel_id(self) -> str:
        return self._config.channel_id

    @property
    def trust_tiers(self) -> frozenset[TrustTier]:
        return self._config.trust_tiers

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        timestamp = str(int(time.time()))
        body = _envelope(message)
        body_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = _sign(self._config.hmac_secret, timestamp, body_bytes)
        headers = {
            "Content-Type": "application/json",
            "X-FDAI-Timestamp": timestamp,
            "X-FDAI-Signature": signature,
            **dict(self._config.extra_headers),
        }
        try:
            response = await self._http.post(
                self._config.url,
                content=body_bytes,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ChannelUnavailableError(
                f"POST {self._config.url} transport error: {exc}"
            ) from exc

        text = truncate(response.text or "")
        if response.status_code >= 400:
            raise ChannelDeliveryError(
                f"POST {self._config.url} → HTTP {response.status_code}: {text!r}"
            )
        return DeliveryReceipt(
            channel_kind=ChannelKind.WEBHOOK,
            channel_id=self._config.channel_id,
            delivered=True,
            provider_message_id=message.correlation_id,
        )


def _envelope(message: NotificationMessage) -> dict[str, object]:
    return {
        "category": message.category,
        "trust_tier": message.trust_tier.value,
        "correlation_id": message.correlation_id,
        "audit_id": message.audit_id,
        "severity": message.severity.value,
        "title": message.title,
        "body_markdown": message.body_markdown,
        "links": [{"label": link.label, "url": link.url} for link in message.links],
        "metadata": dict(message.metadata),
    }


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(
        key=secret.encode("utf-8"),
        msg=timestamp.encode("utf-8") + b"." + body,
        digestmod=hashlib.sha256,
    )
    return "sha256=" + mac.hexdigest()


__all__ = ["GenericWebhookChannel", "GenericWebhookConfig"]
