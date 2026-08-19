"""Fixed-destination, bounded Slack and Teams response publishers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol
from urllib.parse import quote

import httpx
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.models import (
    ChannelDeliveryError,
    ChannelDeliveryReceipt,
    RenderedChannelMessage,
    payload_size,
)
from fdai_operator_service.families.conversation.channel_edge.queues import (
    TeamsEndpointRegistry,
)

_SLACK_POST_URL: Final[str] = "https://slack.com/api/chat.postMessage"
_SLACK_UPDATE_URL: Final[str] = "https://slack.com/api/chat.update"
TEAMS_BOT_SCOPE: Final[str] = "https://api.botframework.com/.default"
_SLACK_RESERVED_KEYS = frozenset({"channel", "ts", "thread_ts"})


@dataclass(frozen=True, slots=True)
class ChannelAccessToken:
    """Carry a secret token plus its non-secret requested audience proof."""

    token: str = field(repr=False)
    audience: str

    def __post_init__(self) -> None:
        if not self.token or not self.audience:
            raise ValueError("channel access token and audience MUST be non-empty")


class ChannelTokenProvider(Protocol):
    """Acquire an outbound token without granting executor authority."""

    async def get_token(self, audience: str) -> ChannelAccessToken: ...


@dataclass(frozen=True, slots=True)
class SlackPublisherConfig:
    """Configure Slack's secret and strict request/response ceilings."""

    bot_token: str = field(repr=False)
    timeout_seconds: float = 10.0
    max_response_bytes: int = 8_192
    max_request_bytes: int = 64_000

    def __post_init__(self) -> None:
        if not self.bot_token:
            raise ValueError("Slack bot_token MUST be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("Slack timeout_seconds MUST be positive")
        if self.max_response_bytes < 64 or self.max_request_bytes < 1:
            raise ValueError("Slack publisher byte limits are invalid")


class SlackResponsePublisher:
    """Send one pre-rendered message through fixed Slack API methods."""

    def __init__(
        self,
        *,
        config: SlackPublisherConfig,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._http = http_client

    async def send(self, message: RenderedChannelMessage) -> ChannelDeliveryReceipt:
        """Publish once and classify whether acknowledgement loss is ambiguous."""
        if message.channel_kind is not ChannelKind.SLACK:
            raise ValueError("Slack publisher requires a Slack message")
        if _SLACK_RESERVED_KEYS.intersection(message.payload):
            raise ChannelDeliveryError(
                "Slack renderer attempted to control routing fields",
                code="reserved_routing_field",
                acknowledgement_ambiguous=False,
            )
        payload = dict(message.payload)
        payload["channel"] = message.channel_id
        if message.edit_message_id is not None:
            url = _SLACK_UPDATE_URL
            payload["ts"] = message.edit_message_id
        else:
            url = _SLACK_POST_URL
            if message.thread_id is not None:
                payload["thread_ts"] = message.thread_id
        if payload_size(payload) > self._config.max_request_bytes:
            raise ChannelDeliveryError(
                "Slack request exceeds the configured byte limit",
                code="request_too_large",
                acknowledgement_ambiguous=False,
            )
        try:
            async with self._http.stream(
                "POST",
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._config.bot_token}",
                    "Accept": "application/json",
                },
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise ChannelDeliveryError(
                        "Slack provider rejected the request",
                        code="provider_rejected",
                        acknowledgement_ambiguous=False,
                    )
                body = await _bounded_body(
                    response.aiter_bytes(),
                    maximum=self._config.max_response_bytes,
                    provider="Slack",
                )
        except ChannelDeliveryError:
            raise
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(
                "Slack acknowledgement was interrupted",
                code="transport_error",
                acknowledgement_ambiguous=True,
            ) from exc
        acknowledgement = _acknowledgement(body, provider="Slack")
        if acknowledgement.get("ok") is not True:
            raise ChannelDeliveryError(
                "Slack provider rejected the request",
                code="provider_rejected",
                acknowledgement_ambiguous=False,
            )
        message_id = acknowledgement.get("ts")
        if not isinstance(message_id, str) or not message_id or len(message_id) > 200:
            raise ChannelDeliveryError(
                "Slack acknowledgement is missing the message id",
                code="invalid_acknowledgement",
                acknowledgement_ambiguous=True,
            )
        return ChannelDeliveryReceipt(
            channel_kind=ChannelKind.SLACK,
            channel_id=message.channel_id,
            message_id=message_id,
            degraded_to_text=message.degraded_to_text,
        )


class TeamsResponsePublisher:
    """Send only through authenticated registry endpoints and fixed Bot scope."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        identity: ChannelTokenProvider,
        endpoints: TeamsEndpointRegistry,
        timeout_seconds: float = 10.0,
        max_request_bytes: int = 32_000,
        max_response_bytes: int = 8_192,
    ) -> None:
        if timeout_seconds <= 0 or max_request_bytes < 1 or max_response_bytes < 64:
            raise ValueError("Teams publisher limits are invalid")
        self._http = http_client
        self._identity = identity
        self._endpoints = endpoints
        self._timeout_seconds = timeout_seconds
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes

    async def send(self, message: RenderedChannelMessage) -> ChannelDeliveryReceipt:
        """Publish once and classify whether acknowledgement loss is ambiguous."""
        if message.channel_kind is not ChannelKind.TEAMS:
            raise ValueError("Teams publisher requires a Teams message")
        service_url = self._endpoints.resolve(message.channel_id)
        if service_url is None:
            raise ChannelDeliveryError(
                "Teams conversation has no authenticated service endpoint",
                code="missing_endpoint",
                acknowledgement_ambiguous=False,
            )
        if payload_size(message.payload) > self._max_request_bytes:
            raise ChannelDeliveryError(
                "Teams request exceeds the configured byte limit",
                code="request_too_large",
                acknowledgement_ambiguous=False,
            )
        conversation = quote(message.channel_id, safe="")
        if message.edit_message_id is None:
            method = "POST"
            url = f"{service_url}/v3/conversations/{conversation}/activities"
        else:
            method = "PUT"
            activity = quote(message.edit_message_id, safe="")
            url = f"{service_url}/v3/conversations/{conversation}/activities/{activity}"
        token = await self._identity.get_token(TEAMS_BOT_SCOPE)
        if token.audience != TEAMS_BOT_SCOPE:
            raise ChannelDeliveryError(
                "Teams identity returned a token for another audience",
                code="identity_audience_mismatch",
                acknowledgement_ambiguous=False,
            )
        try:
            async with self._http.stream(
                method,
                url,
                json=message.payload,
                headers={"Authorization": f"Bearer {token.token}", "Accept": "application/json"},
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code not in {200, 201, 202}:
                    raise ChannelDeliveryError(
                        "Teams provider rejected the request",
                        code="provider_rejected",
                        acknowledgement_ambiguous=False,
                    )
                body = await _bounded_body(
                    response.aiter_bytes(),
                    maximum=self._max_response_bytes,
                    provider="Teams",
                )
        except ChannelDeliveryError:
            raise
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(
                "Teams acknowledgement was interrupted",
                code="transport_error",
                acknowledgement_ambiguous=True,
            ) from exc
        acknowledgement = _acknowledgement(body, provider="Teams")
        message_id = acknowledgement.get("id")
        if not isinstance(message_id, str) or not message_id or len(message_id) > 200:
            raise ChannelDeliveryError(
                "Teams acknowledgement is missing the activity id",
                code="invalid_acknowledgement",
                acknowledgement_ambiguous=True,
            )
        return ChannelDeliveryReceipt(
            channel_kind=ChannelKind.TEAMS,
            channel_id=message.channel_id,
            message_id=message_id,
            degraded_to_text=message.degraded_to_text,
        )


async def _bounded_body(
    chunks: AsyncIterator[bytes],
    *,
    maximum: int,
    provider: str,
) -> bytes:
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
        if len(body) > maximum:
            raise ChannelDeliveryError(
                f"{provider} acknowledgement exceeds the configured byte limit",
                code="acknowledgement_too_large",
                acknowledgement_ambiguous=True,
            )
    return bytes(body)


def _acknowledgement(body: bytes, *, provider: str) -> Mapping[str, Any]:
    try:
        value = json.loads(
            body,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ChannelDeliveryError(
            f"{provider} acknowledgement is invalid JSON",
            code="invalid_acknowledgement",
            acknowledgement_ambiguous=True,
        ) from exc
    if not isinstance(value, Mapping):
        raise ChannelDeliveryError(
            f"{provider} acknowledgement MUST be an object",
            code="invalid_acknowledgement",
            acknowledgement_ambiguous=True,
        )
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


__all__ = [
    "ChannelAccessToken",
    "ChannelTokenProvider",
    "SlackPublisherConfig",
    "SlackResponsePublisher",
    "TEAMS_BOT_SCOPE",
    "TeamsResponsePublisher",
]
