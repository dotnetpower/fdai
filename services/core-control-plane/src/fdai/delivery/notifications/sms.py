"""SMS adapter - Azure Communication Services SMS REST API.

Wire format: POST ``{endpoint}/sms?api-version=2021-03-07`` with an
``Authorization: Bearer <token>`` header. Payload restricted to
``<severity> <audit_id> <short-url>`` per
``docs/roadmap/interfaces/channels-and-notifications.md § 7 (SMS)`` - no free-form
text, no customer identifiers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import httpx

from fdai.shared.providers.notifications.base import (
    ChannelKind,
    DeliveryReceipt,
    NotificationMessage,
    TrustTier,
)

from ._http import post_json

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0
_MAX_SMS_CHARS: Final[int] = 160


@dataclass(frozen=True, slots=True)
class AzureCommunicationSmsConfig:
    channel_id: str
    endpoint: str
    api_version: str = "2021-03-07"
    from_phone_number: str = ""
    to_phone_numbers: tuple[str, ...] = ()
    trust_tiers: frozenset[TrustTier] = frozenset({TrustTier.A2_OPERATIONAL_ALERT})
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


class AzureCommunicationSmsChannel:
    channel_kind: Final = ChannelKind.SMS

    def __init__(
        self,
        *,
        config: AzureCommunicationSmsConfig,
        http_client: httpx.AsyncClient,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not config.endpoint:
            raise ValueError("endpoint MUST NOT be empty")
        if not config.endpoint.startswith("https://"):
            raise ValueError("endpoint MUST use https:// scheme")
        if not config.from_phone_number:
            raise ValueError("from_phone_number MUST NOT be empty")
        if not config.to_phone_numbers:
            raise ValueError("at least one to_phone_numbers entry is required")
        if TrustTier.A1_HIL_APPROVAL in config.trust_tiers:
            raise ValueError("SMS MUST NOT carry A1 approvals")
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
        headers = {"Content-Type": "application/json"}
        if self._token_provider is not None:
            token = self._token_provider()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        url = f"{self._config.endpoint.rstrip('/')}/sms?api-version={self._config.api_version}"
        payload = {
            "from": self._config.from_phone_number,
            "smsRecipients": [{"to": phone} for phone in self._config.to_phone_numbers],
            "message": _sms_body(message),
            "smsSendOptions": {"enableDeliveryReport": True},
        }
        await post_json(
            client=self._http,
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=self._config.timeout_seconds,
            ok_statuses=(200, 202),
        )
        return DeliveryReceipt(
            channel_kind=ChannelKind.SMS,
            channel_id=self._config.channel_id,
            delivered=True,
            provider_message_id=message.correlation_id,
        )


def _sms_body(message: NotificationMessage) -> str:
    """Restrict SMS content to severity + audit id + first runbook link.

    Per the design doc the SMS payload MUST NOT carry free-form text,
    secrets, or customer identifiers - those already-redacted fields
    are the only safe surface.
    """
    parts: list[str] = [message.severity.value.upper()]
    if message.audit_id:
        parts.append(message.audit_id)
    if message.links:
        parts.append(message.links[0].url)
    body = " ".join(parts)
    return body[:_MAX_SMS_CHARS]


__all__ = ["AzureCommunicationSmsChannel", "AzureCommunicationSmsConfig"]
