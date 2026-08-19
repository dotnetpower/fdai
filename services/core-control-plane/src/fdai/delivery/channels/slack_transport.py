"""Bounded queue adapter joining Slack ingress and response publishing."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Final, Protocol, cast

from fdai.delivery.channels.slack_ingress import (
    SlackIngressAction,
    SlackIngressError,
    SlackIngressResult,
    SlackIngressVerifier,
)
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryReceipt,
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)

_CLOSED: Final[object] = object()


class SlackPublisher(Protocol):
    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt: ...


class SlackConversationAdapter:
    """Admit authenticated turns to one bounded queue and publish replies."""

    channel_kind = ConversationChannelKind.SLACK

    def __init__(
        self,
        *,
        ingress: SlackIngressVerifier,
        publisher: SlackPublisher,
        queue_capacity: int = 128,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("Slack queue_capacity MUST be positive")
        self._ingress = ingress
        self._publisher = publisher
        self._queue: asyncio.Queue[InboundTurn | object] = asyncio.Queue(queue_capacity)
        self._closed = False

    def accept(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        received_at: datetime,
    ) -> SlackIngressResult:
        """Verify and enqueue one request without waiting for downstream work."""
        if self._closed:
            raise SlackIngressError(
                "Slack adapter is not accepting requests",
                code="adapter_closed",
                http_status=503,
            )
        result = self._ingress.parse(body=body, headers=headers, received_at=received_at)
        if result.action is SlackIngressAction.ACCEPTED:
            turn = cast(InboundTurn, result.turn)
            try:
                self._queue.put_nowait(turn)
            except asyncio.QueueFull as exc:
                raise SlackIngressError(
                    "Slack ingress queue is full",
                    code="queue_full",
                    http_status=503,
                ) from exc
        return result

    async def receive(self) -> AsyncIterator[InboundTurn]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            yield cast(InboundTurn, item)

    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        return await self._publisher.send(response)

    async def close(self) -> None:
        """Stop admission and wake the single consumer after queued work drains."""
        if self._closed:
            return
        self._closed = True
        await self._queue.put(_CLOSED)


__all__ = ["SlackConversationAdapter", "SlackPublisher"]
