"""Define bounded provider-neutral records for the Operator channel edge."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.contracts import JsonObject

MAX_ATTACHMENT_COUNT = 8
MAX_TEXT_CHARS = 16_000


@dataclass(frozen=True, slots=True)
class ChannelAttachment:
    """Retain only opaque provider metadata for protected attachment ingestion."""

    source_ref: str
    name: str
    size_bytes: int
    media_type_hint: str

    def __post_init__(self) -> None:
        _bounded("attachment source_ref", self.source_ref, 512)
        _bounded("attachment name", self.name, 512)
        _bounded("attachment media_type_hint", self.media_type_hint, 256)
        if isinstance(self.size_bytes, bool) or self.size_bytes < 1:
            raise ValueError("attachment size_bytes MUST be positive")


@dataclass(frozen=True, slots=True)
class InboundChannelTurn:
    """Carry one authenticated provider message without provider URLs or authority."""

    channel_kind: ChannelKind
    channel_id: str
    message_id: str
    sender_id: str
    text: str
    thread_id: str | None = None
    attachments: tuple[ChannelAttachment, ...] = ()

    def __post_init__(self) -> None:
        _bounded("channel_id", self.channel_id, 200)
        _bounded("message_id", self.message_id, 200)
        _bounded("sender_id", self.sender_id, 200)
        if len(self.text) > MAX_TEXT_CHARS:
            raise ValueError("channel message text exceeds the bounded limit")
        if self.thread_id is not None:
            _bounded("thread_id", self.thread_id, 200)
        if len(self.attachments) > MAX_ATTACHMENT_COUNT:
            raise ValueError("channel attachments exceed the bounded count")


@dataclass(frozen=True, slots=True)
class AuthenticatedInboundTurn:
    """Bind one normalized provider turn to a canonical FDAI principal."""

    turn: InboundChannelTurn
    principal_id: str
    verification_ref: str

    def __post_init__(self) -> None:
        _bounded("principal_id", self.principal_id, 256)
        _bounded("verification_ref", self.verification_ref, 512)


@dataclass(frozen=True, slots=True)
class RenderedChannelMessage:
    """Carry one bounded vendor payload plus server-owned routing identity."""

    channel_kind: ChannelKind
    channel_id: str
    payload: JsonObject
    thread_id: str | None = None
    edit_message_id: str | None = None
    degraded_to_text: bool = False

    def __post_init__(self) -> None:
        _bounded("rendered channel_id", self.channel_id, 200)
        if self.thread_id is not None:
            _bounded("rendered thread_id", self.thread_id, 200)
        if self.edit_message_id is not None:
            _bounded("rendered edit_message_id", self.edit_message_id, 200)
        try:
            json.dumps(
                self.payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("rendered channel payload MUST contain valid JSON values") from exc


@dataclass(frozen=True, slots=True)
class ChannelDeliveryReceipt:
    """Retain only the bounded provider acknowledgement needed for durable closure."""

    channel_kind: ChannelKind
    channel_id: str
    message_id: str
    degraded_to_text: bool = False

    def __post_init__(self) -> None:
        _bounded("receipt channel_id", self.channel_id, 200)
        _bounded("receipt message_id", self.message_id, 200)


class ChannelDeliveryError(RuntimeError):
    """Classify provider failure without retaining provider response content."""

    def __init__(self, message: str, *, code: str, acknowledgement_ambiguous: bool) -> None:
        super().__init__(message)
        self.code = code
        self.acknowledgement_ambiguous = acknowledgement_ambiguous


def payload_size(value: JsonObject) -> int:
    """Return strict compact JSON bytes for one provider request bound."""
    return len(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )


def _bounded(name: str, value: str, maximum: int) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} MUST be a non-empty bounded string")


__all__ = [
    "MAX_ATTACHMENT_COUNT",
    "MAX_TEXT_CHARS",
    "AuthenticatedInboundTurn",
    "ChannelAttachment",
    "ChannelDeliveryError",
    "ChannelDeliveryReceipt",
    "ChannelKind",
    "InboundChannelTurn",
    "RenderedChannelMessage",
    "payload_size",
]
