"""Publish canonical A3 responses through fixed Slack Web API methods."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import httpx

from fdai.delivery.channels.artifact import normalize_channel_presentation
from fdai.delivery.channels.common import payload_size
from fdai.delivery.channels.slack import SlackPresentationRenderer
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryError,
    ChannelDeliveryReceipt,
    ChannelThreadMode,
    ConversationChannelKind,
    OutboundResponse,
)

_POST_MESSAGE_URL: Final[str] = "https://slack.com/api/chat.postMessage"
_UPDATE_MESSAGE_URL: Final[str] = "https://slack.com/api/chat.update"
_DEFAULT_TIMEOUT_SECONDS = 10.0
_DEFAULT_MAX_RESPONSE_BYTES = 8_192
_DEFAULT_MAX_REQUEST_BYTES = 64_000


@dataclass(frozen=True, slots=True)
class SlackPublisherConfig:
    """Secret and byte ceilings for the fixed Slack Web API surface."""

    bot_token: str = field(repr=False)
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    max_request_bytes: int = _DEFAULT_MAX_REQUEST_BYTES

    def __post_init__(self) -> None:
        if not self.bot_token:
            raise ValueError("Slack bot_token MUST be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("Slack timeout_seconds MUST be positive")
        if self.max_response_bytes < 64 or self.max_request_bytes < 1:
            raise ValueError("Slack publisher byte limits are invalid")


class SlackResponsePublisher:
    """Render once, send once, and classify the provider acknowledgement."""

    def __init__(
        self,
        *,
        config: SlackPublisherConfig,
        http_client: httpx.AsyncClient,
        renderer: SlackPresentationRenderer | None = None,
    ) -> None:
        self._config = config
        self._http = http_client
        self._renderer = renderer or SlackPresentationRenderer()

    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        if response.channel_kind is not ConversationChannelKind.SLACK:
            raise ValueError("Slack publisher requires a Slack response")
        if response.reaction is not None:
            raise ChannelDeliveryError(
                "Slack reaction delivery is not supported by the A3 publisher",
                code="unsupported_operation",
                acknowledgement_ambiguous=False,
            )
        rendered = self._renderer.render(normalize_channel_presentation(response))
        payload: dict[str, object] = dict(rendered.body)
        payload["channel"] = response.channel_id
        if response.edit_message_id is not None:
            url = _UPDATE_MESSAGE_URL
            payload["ts"] = response.edit_message_id
        else:
            url = _POST_MESSAGE_URL
            if response.thread_mode is ChannelThreadMode.ORIGIN and response.thread_id is not None:
                payload["thread_ts"] = response.thread_id
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
            ) as provider_response:
                body = await _bounded_body(
                    provider_response.aiter_bytes(),
                    maximum=self._config.max_response_bytes,
                )
                status_code = provider_response.status_code
        except ChannelDeliveryError:
            raise
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(
                "Slack acknowledgement was interrupted",
                code="transport_error",
                acknowledgement_ambiguous=True,
            ) from exc
        if status_code != 200:
            raise ChannelDeliveryError(
                "Slack provider rejected the request",
                code="provider_rejected",
                acknowledgement_ambiguous=False,
            )
        acknowledgement = _acknowledgement(body)
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
            channel_kind=ConversationChannelKind.SLACK,
            channel_id=response.channel_id,
            operation=response.operation,
            message_id=message_id,
            degraded_to_text=rendered.degraded_to_text,
        )


async def _bounded_body(chunks: AsyncIterator[bytes], *, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
        if len(body) > maximum:
            raise ChannelDeliveryError(
                "Slack acknowledgement exceeds the configured byte limit",
                code="acknowledgement_too_large",
                acknowledgement_ambiguous=True,
            )
    return bytes(body)


def _acknowledgement(body: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChannelDeliveryError(
            "Slack acknowledgement is invalid JSON",
            code="invalid_acknowledgement",
            acknowledgement_ambiguous=True,
        ) from exc
    if not isinstance(value, Mapping):
        raise ChannelDeliveryError(
            "Slack acknowledgement MUST be an object",
            code="invalid_acknowledgement",
            acknowledgement_ambiguous=True,
        )
    return value


__all__ = ["SlackPublisherConfig", "SlackResponsePublisher"]
