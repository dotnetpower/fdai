"""Join authenticated Slack and Teams ingress to bounded Operator queues."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Final, cast

from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
)
from fdai_operator_service.families.conversation.channel_edge.slack_ingress import (
    SlackIngressAction,
    SlackIngressError,
    SlackIngressResult,
    SlackIngressVerifier,
)
from fdai_operator_service.families.conversation.channel_edge.teams_ingress import (
    TeamsIngressError,
    TeamsIngressVerifier,
    normalize_teams_service_url,
)

_CLOSED: Final[object] = object()


class SlackIngressQueue:
    """Admit authenticated Slack turns to one bounded single-consumer queue."""

    def __init__(self, *, ingress: SlackIngressVerifier, capacity: int = 128) -> None:
        if capacity < 1:
            raise ValueError("Slack queue capacity MUST be positive")
        self._ingress = ingress
        self._queue: asyncio.Queue[AuthenticatedInboundTurn | object] = asyncio.Queue(capacity)
        self._closed = False

    def accept(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        received_at: datetime,
    ) -> SlackIngressResult:
        """Verify and enqueue one request without waiting for semantic work."""
        if self._closed:
            raise SlackIngressError(
                "Slack adapter is not accepting requests",
                code="adapter_closed",
                http_status=503,
            )
        result = self._ingress.parse(body=body, headers=headers, received_at=received_at)
        if result.action is SlackIngressAction.ACCEPTED:
            if (
                result.turn is None
                or result.principal_id is None
                or result.verification_ref is None
            ):
                raise RuntimeError("accepted Slack ingress is missing authenticated context")
            item = AuthenticatedInboundTurn(
                turn=result.turn,
                principal_id=result.principal_id,
                verification_ref=result.verification_ref,
            )
            try:
                self._queue.put_nowait(item)
            except asyncio.QueueFull as exc:
                raise SlackIngressError(
                    "Slack ingress queue is full", code="queue_full", http_status=503
                ) from exc
        return result

    async def receive(self) -> AsyncIterator[AuthenticatedInboundTurn]:
        """Yield accepted turns until shutdown drains and closes the queue."""
        while True:
            if self._closed and self._queue.empty():
                return
            item = await self._queue.get()
            if item is _CLOSED:
                return
            yield cast(AuthenticatedInboundTurn, item)

    async def close(self) -> None:
        """Stop admission and wake the consumer after queued work drains."""
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait(_CLOSED)
        except asyncio.QueueFull:
            pass


class TeamsEndpointRegistry:
    """Retain only authenticated service URLs for bounded conversation ids."""

    def __init__(
        self,
        *,
        allowed_service_urls: frozenset[str],
        maximum: int = 10_000,
    ) -> None:
        if maximum < 1:
            raise ValueError("Teams endpoint registry maximum MUST be positive")
        normalized = frozenset(normalize_teams_service_url(url) for url in allowed_service_urls)
        if not normalized or normalized != allowed_service_urls:
            raise ValueError("Teams endpoint registry requires normalized allowed service URLs")
        self._allowed_service_urls = normalized
        self._maximum = maximum
        self._endpoints: dict[str, str] = {}

    def bind(self, *, conversation_id: str, service_url: str) -> None:
        """Bind one authenticated conversation without allowing endpoint changes."""
        if normalize_teams_service_url(service_url) not in self._allowed_service_urls:
            raise TeamsIngressError(
                "Teams service URL is not authorized",
                code="invalid_service_url",
                http_status=403,
            )
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
        """Resolve only a service URL admitted by authenticated ingress."""
        return self._endpoints.get(conversation_id)


class TeamsIngressQueue:
    """Admit authenticated Teams turns and endpoint bindings to one bounded queue."""

    def __init__(
        self,
        *,
        ingress: TeamsIngressVerifier,
        endpoints: TeamsEndpointRegistry,
        capacity: int = 128,
    ) -> None:
        if capacity < 1:
            raise ValueError("Teams queue capacity MUST be positive")
        self._ingress = ingress
        self._endpoints = endpoints
        self._queue: asyncio.Queue[AuthenticatedInboundTurn | object] = asyncio.Queue(capacity)
        self._closed = False

    async def accept(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> AuthenticatedInboundTurn:
        """Verify and enqueue one activity without binding rejected endpoints."""
        if self._closed:
            raise TeamsIngressError(
                "Teams adapter is not accepting requests",
                code="adapter_closed",
                http_status=503,
            )
        result = await self._ingress.parse(
            body=body,
            authorization=authorization,
            received_at=received_at,
        )
        if self._queue.full():
            raise TeamsIngressError(
                "Teams ingress queue is full", code="queue_full", http_status=503
            )
        self._endpoints.bind(
            conversation_id=result.turn.channel_id,
            service_url=result.service_url,
        )
        item = AuthenticatedInboundTurn(
            turn=result.turn,
            principal_id=result.principal_id,
            verification_ref=result.verification_ref,
        )
        self._queue.put_nowait(item)
        return item

    async def receive(self) -> AsyncIterator[AuthenticatedInboundTurn]:
        """Yield accepted turns until shutdown drains and closes the queue."""
        while True:
            if self._closed and self._queue.empty():
                return
            item = await self._queue.get()
            if item is _CLOSED:
                return
            yield cast(AuthenticatedInboundTurn, item)

    async def close(self) -> None:
        """Stop admission and wake the consumer after queued work drains."""
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait(_CLOSED)
        except asyncio.QueueFull:
            pass


__all__ = ["SlackIngressQueue", "TeamsEndpointRegistry", "TeamsIngressQueue"]
