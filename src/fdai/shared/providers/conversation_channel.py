"""Bidirectional operator conversation channel contract."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, cast, runtime_checkable

MAX_CHANNEL_ID_CHARS = 200
MAX_MESSAGE_ID_CHARS = 200
MAX_SENDER_ID_CHARS = 200
MAX_TEXT_CHARS = 16_000
MAX_THREAD_ID_CHARS = 200
MAX_ATTACHMENT_COUNT = 8
MAX_ATTACHMENT_REF_CHARS = 512
MAX_ATTACHMENT_NAME_CHARS = 512
MAX_MEDIA_TYPE_CHARS = 256
MAX_MENTION_COUNT = 20
MAX_STREAM_CHUNKS = 128


class ConversationChannelKind(StrEnum):
    TEAMS = "teams"
    SLACK = "slack"
    WEB = "web"


class ChannelDeliveryOperation(StrEnum):
    POST = "post"
    STREAM = "stream"
    EDIT = "edit"
    REACTION = "reaction"


class ChannelThreadMode(StrEnum):
    ORIGIN = "origin"
    DEDICATED = "dedicated"


class ChannelDeliveryError(RuntimeError):
    """A provider send failed with an explicit acknowledgement risk classification."""

    def __init__(self, message: str, *, code: str, acknowledgement_ambiguous: bool) -> None:
        super().__init__(message)
        self.code = code
        self.acknowledgement_ambiguous = acknowledgement_ambiguous


@dataclass(frozen=True, slots=True)
class ChannelMention:
    """Opaque vendor principal target plus safe text fallback label."""

    target_id: str
    display_text: str

    def __post_init__(self) -> None:
        _bounded("mention.target_id", self.target_id, MAX_SENDER_ID_CHARS)
        _bounded("mention.display_text", self.display_text, MAX_SENDER_ID_CHARS)


@dataclass(frozen=True, slots=True)
class ChannelDeliveryReceipt:
    """Vendor acknowledgement returned only after an accepted delivery."""

    channel_kind: ConversationChannelKind
    channel_id: str
    operation: ChannelDeliveryOperation
    message_id: str | None
    degraded_to_text: bool = False

    def __post_init__(self) -> None:
        _bounded("receipt.channel_id", self.channel_id, MAX_CHANNEL_ID_CHARS)
        if self.message_id is not None:
            _bounded("receipt.message_id", self.message_id, MAX_MESSAGE_ID_CHARS)


@dataclass(frozen=True, slots=True)
class ChannelAttachment:
    """Untrusted vendor attachment metadata; source bytes remain out of core."""

    source_ref: str
    name: str
    size_bytes: int
    media_type_hint: str

    def __post_init__(self) -> None:
        _bounded("attachment.source_ref", self.source_ref, MAX_ATTACHMENT_REF_CHARS)
        _bounded("attachment.name", self.name, MAX_ATTACHMENT_NAME_CHARS)
        _bounded("attachment.media_type_hint", self.media_type_hint, MAX_MEDIA_TYPE_CHARS)
        if self.size_bytes < 1:
            raise ValueError("ChannelAttachment.size_bytes MUST be positive")


@dataclass(frozen=True, slots=True)
class InboundTurn:
    """Normalized untrusted message received from one channel wire."""

    channel_kind: ConversationChannelKind
    channel_id: str
    message_id: str
    sender_id: str
    text: str
    thread_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    attachments: tuple[ChannelAttachment, ...] = ()

    def __post_init__(self) -> None:
        _bounded("channel_id", self.channel_id, MAX_CHANNEL_ID_CHARS)
        _bounded("message_id", self.message_id, MAX_MESSAGE_ID_CHARS)
        _bounded("sender_id", self.sender_id, MAX_SENDER_ID_CHARS)
        _bounded("text", self.text, MAX_TEXT_CHARS)
        if self.thread_id is not None:
            _bounded("thread_id", self.thread_id, MAX_THREAD_ID_CHARS)
        if len(self.attachments) > MAX_ATTACHMENT_COUNT:
            raise ValueError(
                f"InboundTurn.attachments exceeds cap ({len(self.attachments)} > "
                f"{MAX_ATTACHMENT_COUNT})"
            )


@dataclass(frozen=True, slots=True)
class OutboundResponse:
    """Channel-neutral response routed back to the originating thread."""

    channel_kind: ConversationChannelKind
    channel_id: str
    in_reply_to: str
    thread_id: str | None
    status: str
    text: str
    data: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    mentions: tuple[ChannelMention, ...] = ()
    stream_chunks: tuple[str, ...] = ()
    edit_message_id: str | None = None
    reaction: str | None = None
    thread_mode: ChannelThreadMode = ChannelThreadMode.ORIGIN

    def __post_init__(self) -> None:
        _bounded("channel_id", self.channel_id, MAX_CHANNEL_ID_CHARS)
        _bounded("in_reply_to", self.in_reply_to, MAX_MESSAGE_ID_CHARS)
        _bounded("status", self.status, 64)
        _bounded("text", self.text, MAX_TEXT_CHARS)
        if self.thread_id is not None:
            _bounded("thread_id", self.thread_id, MAX_THREAD_ID_CHARS)
        if len(self.mentions) > MAX_MENTION_COUNT:
            raise ValueError("OutboundResponse.mentions exceeds cap")
        if len(self.stream_chunks) > MAX_STREAM_CHUNKS:
            raise ValueError("OutboundResponse.stream_chunks exceeds cap")
        if any(not chunk or not chunk.strip() for chunk in self.stream_chunks):
            raise ValueError("OutboundResponse.stream_chunks MUST be non-empty")
        if sum(len(chunk) for chunk in self.stream_chunks) > MAX_TEXT_CHARS:
            raise ValueError("OutboundResponse.stream_chunks exceeds text cap")
        if self.edit_message_id is not None:
            _bounded("edit_message_id", self.edit_message_id, MAX_MESSAGE_ID_CHARS)
        if self.reaction is not None:
            _bounded("reaction", self.reaction, 64)
            if self.mentions:
                raise ValueError("OutboundResponse reactions cannot carry mentions")
        if self.thread_mode is ChannelThreadMode.DEDICATED and self.thread_id is not None:
            raise ValueError("dedicated thread delivery cannot declare an existing thread_id")
        rich_modes = sum(
            (
                bool(self.stream_chunks),
                self.edit_message_id is not None,
                self.reaction is not None,
            )
        )
        if rich_modes > 1:
            raise ValueError("OutboundResponse rich delivery modes are mutually exclusive")

    @property
    def operation(self) -> ChannelDeliveryOperation:
        if self.stream_chunks:
            return ChannelDeliveryOperation.STREAM
        if self.edit_message_id is not None:
            return ChannelDeliveryOperation.EDIT
        if self.reaction is not None:
            return ChannelDeliveryOperation.REACTION
        return ChannelDeliveryOperation.POST


@runtime_checkable
class ConversationChannelAdapter(Protocol):
    """Receive and send turns on one bidirectional vendor wire."""

    channel_kind: ConversationChannelKind

    def receive(self) -> AsyncIterator[InboundTurn]: ...

    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt | None: ...


def outbound_response_to_json(response: OutboundResponse) -> dict[str, Any]:
    """Serialize the complete bounded response for durable replay."""
    return {
        "channel_kind": response.channel_kind.value,
        "channel_id": response.channel_id,
        "in_reply_to": response.in_reply_to,
        "thread_id": response.thread_id,
        "status": response.status,
        "text": response.text,
        "data": dict(response.data),
        "evidence_refs": list(response.evidence_refs),
        "mentions": [
            {"target_id": mention.target_id, "display_text": mention.display_text}
            for mention in response.mentions
        ],
        "stream_chunks": list(response.stream_chunks),
        "edit_message_id": response.edit_message_id,
        "reaction": response.reaction,
        "thread_mode": response.thread_mode.value,
    }


def outbound_response_from_json(value: object) -> OutboundResponse:
    """Decode a stored response and reapply every boundary invariant."""
    if not isinstance(value, Mapping):
        raise ValueError("stored outbound response MUST be an object")
    mentions = value.get("mentions", ())
    if not isinstance(mentions, list) or any(not isinstance(item, Mapping) for item in mentions):
        raise ValueError("stored outbound response mentions MUST be objects")
    data = value.get("data", {})
    if not isinstance(data, Mapping):
        raise ValueError("stored outbound response data MUST be an object")
    return OutboundResponse(
        channel_kind=ConversationChannelKind(str(value["channel_kind"])),
        channel_id=str(value["channel_id"]),
        in_reply_to=str(value["in_reply_to"]),
        thread_id=str(value["thread_id"]) if value.get("thread_id") is not None else None,
        status=str(value["status"]),
        text=str(value["text"]),
        data=cast(Mapping[str, Any], data),
        evidence_refs=tuple(str(item) for item in value.get("evidence_refs", ())),
        mentions=tuple(
            ChannelMention(
                target_id=str(item["target_id"]),
                display_text=str(item["display_text"]),
            )
            for item in cast(list[Mapping[str, object]], mentions)
        ),
        stream_chunks=tuple(str(item) for item in value.get("stream_chunks", ())),
        edit_message_id=(
            str(value["edit_message_id"]) if value.get("edit_message_id") is not None else None
        ),
        reaction=str(value["reaction"]) if value.get("reaction") is not None else None,
        thread_mode=ChannelThreadMode(str(value.get("thread_mode", "origin"))),
    )


def _bounded(name: str, value: str, maximum: int) -> None:
    if not value or not value.strip():
        raise ValueError(f"InboundTurn.{name} MUST be non-empty")
    if len(value) > maximum:
        raise ValueError(f"InboundTurn.{name} exceeds cap ({len(value)} > {maximum})")


__all__ = [
    "ChannelAttachment",
    "ChannelDeliveryOperation",
    "ChannelDeliveryError",
    "ChannelDeliveryReceipt",
    "ChannelMention",
    "ChannelThreadMode",
    "ConversationChannelAdapter",
    "ConversationChannelKind",
    "InboundTurn",
    "MAX_ATTACHMENT_COUNT",
    "MAX_MENTION_COUNT",
    "MAX_STREAM_CHUNKS",
    "OutboundResponse",
    "outbound_response_from_json",
    "outbound_response_to_json",
]
