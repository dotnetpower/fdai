"""Bounded Teams adapter and fixed Bot Connector response publisher."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Final, cast
from urllib.parse import quote

import httpx

from fdai.delivery.channels.artifact import normalize_channel_presentation
from fdai.delivery.channels.common import payload_size
from fdai.delivery.channels.teams import TeamsPresentationRenderer
from fdai.delivery.channels.teams_ingress import (
    TeamsIngressError,
    TeamsIngressVerifier,
)
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryError,
    ChannelDeliveryReceipt,
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_BOT_AUDIENCE: Final[str] = "https://api.botframework.com/.default"
_CLOSED: Final[object] = object()


class TeamsEndpointRegistry:
    """Retain only authenticated service URLs for bounded conversation ids."""

    def __init__(self, *, maximum: int = 10_000) -> None:
        if maximum < 1:
            raise ValueError("Teams endpoint registry maximum MUST be positive")
        self._maximum = maximum
        self._endpoints: dict[str, str] = {}

    def bind(self, *, conversation_id: str, service_url: str) -> None:
        current = self._endpoints.get(conversation_id)
        if current is not None and current != service_url:
            raise TeamsIngressError(
                "Teams conversation service URL changed unexpectedly",
                code="service_url_changed",
                http_status=409,
            )
        if current is None and len(self._endpoints) >= self._maximum:
            raise TeamsIngressError(
                "Teams endpoint registry is full",
                code="endpoint_registry_full",
                http_status=503,
            )
        self._endpoints[conversation_id] = service_url

    def resolve(self, conversation_id: str) -> str | None:
        return self._endpoints.get(conversation_id)


class TeamsResponsePublisher:
    """Publish through an authenticated registry endpoint and strict acknowledgement."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        identity: WorkloadIdentity,
        endpoints: TeamsEndpointRegistry,
        renderer: TeamsPresentationRenderer | None = None,
        timeout_seconds: float = 10.0,
        max_request_bytes: int = 32_000,
        max_response_bytes: int = 8_192,
    ) -> None:
        if timeout_seconds <= 0 or max_request_bytes < 1 or max_response_bytes < 64:
            raise ValueError("Teams publisher limits are invalid")
        self._http = http_client
        self._identity = identity
        self._endpoints = endpoints
        self._renderer = renderer or TeamsPresentationRenderer()
        self._timeout_seconds = timeout_seconds
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes

    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        if response.channel_kind is not ConversationChannelKind.TEAMS:
            raise ValueError("Teams publisher requires a Teams response")
        if response.reaction is not None:
            raise ChannelDeliveryError(
                "Teams reaction delivery is not supported by the A3 publisher",
                code="unsupported_operation",
                acknowledgement_ambiguous=False,
            )
        service_url = self._endpoints.resolve(response.channel_id)
        if service_url is None:
            raise ChannelDeliveryError(
                "Teams conversation has no authenticated service endpoint",
                code="missing_endpoint",
                acknowledgement_ambiguous=False,
            )
        rendered = self._renderer.render(normalize_channel_presentation(response))
        payload = dict(rendered.body)
        if payload_size(payload) > self._max_request_bytes:
            raise ChannelDeliveryError(
                "Teams request exceeds the configured byte limit",
                code="request_too_large",
                acknowledgement_ambiguous=False,
            )
        conversation = quote(response.channel_id, safe="")
        if response.edit_message_id is None:
            url = f"{service_url}/v3/conversations/{conversation}/activities"
        else:
            activity = quote(response.edit_message_id, safe="")
            url = f"{service_url}/v3/conversations/{conversation}/activities/{activity}"
        token = await self._identity.get_token(_BOT_AUDIENCE)
        if token.audience != _BOT_AUDIENCE:
            raise ChannelDeliveryError(
                "Teams identity returned a token for another audience",
                code="identity_audience_mismatch",
                acknowledgement_ambiguous=False,
            )
        try:
            async with self._http.stream(
                "POST" if response.edit_message_id is None else "PUT",
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token.token}", "Accept": "application/json"},
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as provider_response:
                body = await _bounded_body(
                    provider_response.aiter_bytes(), maximum=self._max_response_bytes
                )
                status_code = provider_response.status_code
        except ChannelDeliveryError:
            raise
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(
                "Teams acknowledgement was interrupted",
                code="transport_error",
                acknowledgement_ambiguous=True,
            ) from exc
        if status_code not in {200, 201, 202}:
            raise ChannelDeliveryError(
                "Teams provider rejected the request",
                code="provider_rejected",
                acknowledgement_ambiguous=False,
            )
        try:
            acknowledgement = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ChannelDeliveryError(
                "Teams acknowledgement is invalid JSON",
                code="invalid_acknowledgement",
                acknowledgement_ambiguous=True,
            ) from exc
        message_id = acknowledgement.get("id") if isinstance(acknowledgement, dict) else None
        if not isinstance(message_id, str) or not message_id or len(message_id) > 200:
            raise ChannelDeliveryError(
                "Teams acknowledgement is missing the activity id",
                code="invalid_acknowledgement",
                acknowledgement_ambiguous=True,
            )
        return ChannelDeliveryReceipt(
            channel_kind=ConversationChannelKind.TEAMS,
            channel_id=response.channel_id,
            operation=response.operation,
            message_id=message_id,
            degraded_to_text=rendered.degraded_to_text,
        )


class TeamsConversationAdapter:
    """Admit authenticated activities to one bounded queue and publish replies."""

    channel_kind = ConversationChannelKind.TEAMS

    def __init__(
        self,
        *,
        ingress: TeamsIngressVerifier,
        publisher: TeamsResponsePublisher,
        endpoints: TeamsEndpointRegistry,
        queue_capacity: int = 128,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("Teams queue_capacity MUST be positive")
        self._ingress = ingress
        self._publisher = publisher
        self._endpoints = endpoints
        self._queue: asyncio.Queue[InboundTurn | object] = asyncio.Queue(queue_capacity)
        self._closed = False

    async def accept(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> tuple[str, str]:
        if self._closed:
            raise TeamsIngressError(
                "Teams adapter is not accepting requests",
                code="adapter_closed",
                http_status=503,
            )
        result = await self._ingress.parse(
            body=body, authorization=authorization, received_at=received_at
        )
        if self._queue.full():
            raise TeamsIngressError(
                "Teams ingress queue is full",
                code="queue_full",
                http_status=503,
            )
        self._endpoints.bind(
            conversation_id=result.turn.channel_id,
            service_url=result.service_url,
        )
        self._queue.put_nowait(result.turn)
        return result.principal_id, result.verification_ref

    async def receive(self) -> AsyncIterator[InboundTurn]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            yield cast(InboundTurn, item)

    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        return await self._publisher.send(response)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(_CLOSED)


async def _bounded_body(chunks: AsyncIterator[bytes], *, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
        if len(body) > maximum:
            raise ChannelDeliveryError(
                "Teams acknowledgement exceeds the configured byte limit",
                code="acknowledgement_too_large",
                acknowledgement_ambiguous=True,
            )
    return bytes(body)


__all__ = [
    "TeamsConversationAdapter",
    "TeamsEndpointRegistry",
    "TeamsResponsePublisher",
]
