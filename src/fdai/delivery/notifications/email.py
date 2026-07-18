"""Email adapter - Azure Communication Services Email REST API.

Send-only. Never carries an approval action; the adapter refuses A1
traffic at composition time (the channel's ``trust_tiers`` frozenset
never includes :attr:`TrustTier.A1_HIL_APPROVAL`).

Wire format: POST ``{endpoint}/emails:send?api-version=2023-03-31``
with an ``Authorization: Bearer <token>`` header. The bearer token is
supplied per call - the composition root fetches it through the
:class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
seam and hands it in on adapter construction so this module never
touches Azure SDKs directly (keeps the CSP-neutrality gate happy).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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

from ._http import post_json_response, truncate

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0
_DEFAULT_POLL_INTERVAL_SECONDS: Final[float] = 1.0
_DEFAULT_MAX_POLL_ATTEMPTS: Final[int] = 60


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
    poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS
    max_poll_attempts: int = _DEFAULT_MAX_POLL_ATTEMPTS


class AzureCommunicationEmailChannel:
    """Sends email via Azure Communication Services (send-only)."""

    channel_kind: Final = ChannelKind.EMAIL

    def __init__(
        self,
        *,
        config: AzureCommunicationEmailConfig,
        http_client: httpx.AsyncClient,
        token_provider: Callable[[], str | Awaitable[str]] | None = None,
    ) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if config.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds MUST be >= 0")
        if config.max_poll_attempts < 1:
            raise ValueError("max_poll_attempts MUST be >= 1")
        if not config.endpoint:
            raise ValueError("endpoint MUST NOT be empty")
        if not config.endpoint.startswith("https://"):
            # Azure Communication Services email endpoint is always
            # HTTPS; refuse http:// so a fork misconfiguration does not
            # push a bearer token in the clear.
            raise ValueError("endpoint MUST use https:// scheme")
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
            if inspect.isawaitable(token):
                token = await token
            if token:
                headers["Authorization"] = f"Bearer {token}"
        endpoint = self._config.endpoint.rstrip("/")
        url = f"{endpoint}/emails:send?api-version={self._config.api_version}"
        payload = _acs_email_payload(message, self._config)
        response = await post_json_response(
            client=self._http,
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=self._config.timeout_seconds,
            ok_statuses=(200, 202),
        )
        provider_message_id = message.correlation_id
        if response.status_code == 202:
            operation_url = response.headers.get("Operation-Location", "").strip()
            if not operation_url:
                raise ChannelDeliveryError(
                    "ACS Email accepted the request without an Operation-Location header"
                )
            if not operation_url.startswith(f"{endpoint}/"):
                raise ChannelDeliveryError(
                    "ACS Email returned an operation URL outside the configured endpoint"
                )
            provider_message_id = await self._wait_for_delivery(
                operation_url=operation_url,
                headers=headers,
                fallback_id=message.correlation_id,
            )
        return DeliveryReceipt(
            channel_kind=ChannelKind.EMAIL,
            channel_id=self._config.channel_id,
            delivered=True,
            provider_message_id=provider_message_id,
        )

    async def _wait_for_delivery(
        self,
        *,
        operation_url: str,
        headers: dict[str, str],
        fallback_id: str,
    ) -> str:
        for attempt in range(self._config.max_poll_attempts):
            try:
                response = await self._http.get(
                    operation_url,
                    headers=headers,
                    timeout=self._config.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise ChannelUnavailableError(
                    f"GET {operation_url} transport error: {exc}"
                ) from exc
            if response.status_code != 200:
                raise ChannelDeliveryError(
                    f"GET {operation_url} -> HTTP {response.status_code}: "
                    f"{truncate(response.text or '')!r}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ChannelDeliveryError(
                    "ACS Email operation returned an invalid JSON response"
                ) from exc
            status = str(payload.get("status", ""))
            provider_message_id = str(payload.get("id") or fallback_id)
            if status == "Succeeded":
                return provider_message_id
            if status in {"Failed", "Canceled"}:
                error = truncate(str(payload.get("error") or "unknown provider error"))
                raise ChannelDeliveryError(
                    f"ACS Email operation {provider_message_id} ended as {status}: {error}"
                )
            if attempt + 1 < self._config.max_poll_attempts:
                await asyncio.sleep(self._config.poll_interval_seconds)
        raise ChannelUnavailableError(
            "ACS Email operation did not complete within the configured poll budget"
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
            "x-fdai-correlation-id": message.correlation_id,
            **({"x-fdai-audit-id": message.audit_id} if message.audit_id else {}),
        },
    }


__all__ = ["AzureCommunicationEmailChannel", "AzureCommunicationEmailConfig"]
