"""Email adapter — Azure Communication Services Email REST API.

Send-only. Never carries an approval action; the adapter refuses A1
traffic at composition time (the channel's ``trust_tiers`` frozenset
never includes :attr:`TrustTier.A1_HIL_APPROVAL`).

Wire format: POST ``{endpoint}/emails:send?api-version=2023-03-31``
with an ``Authorization: Bearer <token>`` header. The bearer token is
supplied per call — the composition root fetches it through the
:class:`~aiopspilot.shared.providers.workload_identity.WorkloadIdentity`
seam and hands it in on adapter construction so this module never
touches Azure SDKs directly (keeps the CSP-neutrality gate happy).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import httpx

from aiopspilot.shared.providers.notifications.base import (
    ChannelKind,
    DeliveryReceipt,
    NotificationMessage,
    TrustTier,
)

from ._http import post_json

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0


@dataclass(frozen=True, slots=True)
class AzureCommunicationEmailConfig:
    """ACS Email endpoint + sender + recipient list."""

    channel_id: str
    endpoint: str
    """ACS resource endpoint, e.g. ``https://acs-notify.communication.azure.com``."""

    api_version: str = "2023-03-31"
    sender_address: str = "no-reply@example.com"
    recipient_addresses: tuple[str, ...] = ()
    trust_tiers: frozenset[TrustTier] = frozenset(
        {TrustTier.A2_OPERATIONAL_ALERT, TrustTier.A4_DIGEST}
    )
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


class AzureCommunicationEmailChannel:
    """Sends email via Azure Communication Services (send-only)."""

    channel_kind: Final = ChannelKind.EMAIL

    def __init__(
        self,
        *,
        config: AzureCommunicationEmailConfig,
        http_client: httpx.AsyncClient,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not config.endpoint:
            raise ValueError("endpoint MUST NOT be empty")
        if not config.recipient_addresses:
            raise ValueError("at least one recipient_addresses entry is required")
        if TrustTier.A1_HIL_APPROVAL in config.trust_tiers:
            raise ValueError(
                "email channel MUST NOT carry A1 approvals (magic-link approvals prohibited)"
            )
        self._config: Final = config
        self._http: Final = http_client
        self._token_provider: Final = token_provider

    @property
    def channel_id(self) -> str:
        return self._config.channel_id

    @property
    def trust_tiers(self) -> frozenset[TrustTier]:
        return self._config.trust_tiers

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        headers = {
            "Content-Type": "application/json",
        }
        if self._token_provider is not None:
            token = self._token_provider()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        endpoint = self._config.endpoint.rstrip("/")
        url = f"{endpoint}/emails:send?api-version={self._config.api_version}"
        payload = _acs_email_payload(message, self._config)
        await post_json(
            client=self._http,
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=self._config.timeout_seconds,
            ok_statuses=(200, 202),
        )
        return DeliveryReceipt(
            channel_kind=ChannelKind.EMAIL,
            channel_id=self._config.channel_id,
            delivered=True,
            provider_message_id=message.correlation_id,
        )


def _acs_email_payload(
    message: NotificationMessage,
    config: AzureCommunicationEmailConfig,
) -> dict[str, object]:
    return {
        "senderAddress": config.sender_address,
        "content": {
            "subject": message.title[:255],
            "plainText": message.body_markdown,
        },
        "recipients": {
            "to": [{"address": addr} for addr in config.recipient_addresses],
        },
        "headers": {
            "x-aiopspilot-correlation-id": message.correlation_id,
            **({"x-aiopspilot-audit-id": message.audit_id} if message.audit_id else {}),
        },
    }


__all__ = ["AzureCommunicationEmailChannel", "AzureCommunicationEmailConfig"]
