"""Authenticated Bot Framework activity adapter for Teams conversations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fdai.shared.providers.conversation_channel import (
    MAX_ATTACHMENT_COUNT,
    ChannelAttachment,
    ChannelDeliveryReceipt,
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)


class TeamsReplyPublisher(Protocol):
    """Publish through a configured Bot Framework conversation client."""

    async def publish(self, response: OutboundResponse) -> ChannelDeliveryReceipt: ...


@dataclass(frozen=True, slots=True)
class TeamsIngressResult:
    accepted: bool
    reason: str


class TeamsBotChannel:
    """Normalize JWT-authenticated Bot Framework activities and publish replies."""

    channel_kind = ConversationChannelKind.TEAMS

    def __init__(self, *, publisher: TeamsReplyPublisher, queue_capacity: int = 256) -> None:
        if queue_capacity <= 0:
            raise ValueError("TeamsBotChannel.queue_capacity MUST be positive")
        self._publisher = publisher
        self._queue: asyncio.Queue[InboundTurn | None] = asyncio.Queue(queue_capacity)
        self._closed = False

    async def accept_authenticated_activity(
        self,
        *,
        activity: Mapping[str, Any],
        principal_id: str | None = None,
    ) -> TeamsIngressResult:
        """Enqueue an activity only after the HTTP route validates its bearer JWT."""
        if self._closed:
            return TeamsIngressResult(False, "channel closed")
        turn = _normalize_activity(activity, principal_id=principal_id)
        if turn is None:
            return TeamsIngressResult(False, "ignored activity")
        try:
            self._queue.put_nowait(turn)
        except asyncio.QueueFull:
            return TeamsIngressResult(False, "channel queue full")
        return TeamsIngressResult(True, "accepted")

    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        if response.channel_kind is not self.channel_kind:
            raise ValueError("Teams response channel kind mismatch")
        return await self._publisher.publish(response)

    async def receive(self) -> AsyncIterator[InboundTurn]:
        while True:
            if self._closed and self._queue.empty():
                return
            turn = await self._queue.get()
            if turn is None:
                return
            yield turn

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._queue.full():
            self._queue.put_nowait(None)


def _normalize_activity(
    activity: Mapping[str, Any],
    *,
    principal_id: str | None = None,
) -> InboundTurn | None:
    if activity.get("type") != "message":
        return None
    sender = activity.get("from")
    conversation = activity.get("conversation")
    if not isinstance(sender, Mapping) or not isinstance(conversation, Mapping):
        return None
    if sender.get("role") == "bot":
        return None
    sender_id = sender.get("aadObjectId") or sender.get("id")
    channel_id = conversation.get("id")
    message_id = activity.get("id")
    text = activity.get("text")
    if not isinstance(sender_id, str) or not sender_id:
        return None
    if not isinstance(channel_id, str) or not channel_id:
        return None
    if not isinstance(message_id, str) or not message_id:
        return None
    if not isinstance(text, str) or not text:
        return None
    attachments = _normalize_attachments(activity.get("attachments"))
    if attachments is None:
        return None
    reply_to = activity.get("replyToId")
    return InboundTurn(
        channel_kind=ConversationChannelKind.TEAMS,
        channel_id=channel_id,
        message_id=message_id,
        sender_id=sender_id,
        text=text,
        thread_id=reply_to if isinstance(reply_to, str) and reply_to else message_id,
        metadata=({"verified_principal_id": principal_id} if principal_id is not None else {}),
        attachments=attachments,
    )


def _normalize_attachments(raw: Any) -> tuple[ChannelAttachment, ...] | None:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_ATTACHMENT_COUNT:
        return None
    attachments: list[ChannelAttachment] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return None
        content = item.get("content")
        content_map = content if isinstance(content, Mapping) else {}
        source_ref = item.get("id") or content_map.get("id")
        name = item.get("name") or content_map.get("name")
        size = item.get("size") or content_map.get("size")
        media_type = item.get("contentType")
        if (
            not isinstance(source_ref, str)
            or not isinstance(name, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(media_type, str)
        ):
            return None
        try:
            attachments.append(
                ChannelAttachment(
                    source_ref=source_ref,
                    name=name,
                    size_bytes=size,
                    media_type_hint=media_type,
                )
            )
        except ValueError:
            return None
    return tuple(attachments)


__all__ = ["TeamsBotChannel", "TeamsIngressResult", "TeamsReplyPublisher"]
