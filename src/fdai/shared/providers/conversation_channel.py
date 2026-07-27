"""Bidirectional operator conversation channel contract."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, cast, runtime_checkable
from unicodedata import category

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
MAX_PROGRESS_UPDATES = 128
MAX_ACTIVITY_COUNT = 16
MAX_ACTIVITY_AGENT_CHARS = 64
MAX_ACTIVITY_LABEL_CHARS = 256
MAX_ACTIVITY_TASK_CHARS = 512
MAX_ACTIVITY_TOOL_CHARS = 64
MAX_ACTIVITY_COMMAND_CHARS = 8_192
MAX_ACTIVITY_OUTPUT_CHARS = 12_000
MAX_ACTIVITY_TOTAL_CHARS = 48_000

_SENSITIVE_ACTIVITY_TEXT = re.compile(
    r"(?i)\bbearer(?:\s+|[:=_-]+)[a-z0-9._~+/=-]{6,}"
    r"|\b(?:password|secret|token|api[_-]?key)\s*[:=]\s*"
    r"(?!\[redacted\]|<redacted>)[^\s,;]{6,}"
    r"|\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"
    r"|/subscriptions/|/resourceGroups/"
    r"|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    r"|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


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


class ConversationExecutionStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ChannelProgressStatus(StrEnum):
    RUNNING = "running"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class AgentHandoffActivity:
    """Visible Bragi routing handoff without direct-call authority."""

    from_agent: str
    to_agent: str
    task: str
    trace_ref: str | None = None

    def __post_init__(self) -> None:
        _bounded("activity.from_agent", self.from_agent, MAX_ACTIVITY_AGENT_CHARS)
        _bounded("activity.to_agent", self.to_agent, MAX_ACTIVITY_AGENT_CHARS)
        _safe_bounded("activity.task", self.task, MAX_ACTIVITY_TASK_CHARS)
        if self.trace_ref is not None:
            _bounded("activity.trace_ref", self.trace_ref, MAX_MESSAGE_ID_CHARS)


@dataclass(frozen=True, slots=True)
class ObservedExecutionActivity:
    """Redacted read-operation evidence rendered consistently across channels."""

    agent: str
    label: str
    tool: str
    command: str
    status: ConversationExecutionStatus
    redacted: Literal[True]
    output: str = ""
    output_truncated: bool = False
    exit_code: int | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    authority: str | None = None

    def __post_init__(self) -> None:
        _bounded("activity.agent", self.agent, MAX_ACTIVITY_AGENT_CHARS)
        _safe_bounded("activity.label", self.label, MAX_ACTIVITY_LABEL_CHARS)
        _safe_bounded("activity.tool", self.tool, MAX_ACTIVITY_TOOL_CHARS)
        _safe_bounded("activity.command", self.command, MAX_ACTIVITY_COMMAND_CHARS)
        if self.redacted is not True:
            raise ValueError("ObservedExecutionActivity.redacted MUST be true")
        if self.output:
            _safe_bounded("activity.output", self.output, MAX_ACTIVITY_OUTPUT_CHARS)
        if self.exit_code is not None and not -(2**31) <= self.exit_code < 2**31:
            raise ValueError("activity.exit_code MUST be a signed 32-bit integer")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("activity.duration_ms MUST be non-negative")
        for name, value in (
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
        ):
            if value is not None:
                _bounded(f"activity.{name}", value, MAX_ACTIVITY_LABEL_CHARS)
                _rfc3339(f"activity.{name}", value)
        if self.started_at is not None and self.completed_at is not None:
            if _rfc3339("activity.completed_at", self.completed_at) < _rfc3339(
                "activity.started_at", self.started_at
            ):
                raise ValueError("activity.completed_at MUST NOT precede activity.started_at")
        if self.authority is not None:
            _safe_bounded("activity.authority", self.authority, MAX_ACTIVITY_LABEL_CHARS)


ConversationActivity = AgentHandoffActivity | ObservedExecutionActivity


@dataclass(frozen=True, slots=True)
class ChannelProgressUpdate:
    """One cumulative coordinator snapshot for monotonic provider editing."""

    revision: int
    status: ChannelProgressStatus
    text: str
    activity_count: int

    def __post_init__(self) -> None:
        if not 0 <= self.revision < MAX_PROGRESS_UPDATES:
            raise ValueError("channel progress revision is outside the bounded range")
        _safe_bounded("channel progress text", self.text, MAX_TEXT_CHARS)
        if not 0 <= self.activity_count <= MAX_ACTIVITY_COUNT:
            raise ValueError("channel progress activity_count is outside the bounded range")


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
        if self.name in {".", ".."} or any(
            character in {"/", "\\"} or category(character).startswith("C")
            for character in self.name
        ):
            raise ValueError("ChannelAttachment.name MUST be a safe leaf name")
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
        if len(self.text) > MAX_TEXT_CHARS:
            raise ValueError(f"InboundTurn.text exceeds cap ({len(self.text)} > {MAX_TEXT_CHARS})")
        if not self.text.strip() and not self.attachments:
            raise ValueError("InboundTurn requires text or at least one attachment")
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
    activities: tuple[ConversationActivity, ...] = ()
    stream_chunks: tuple[str, ...] = ()
    progress_updates: tuple[ChannelProgressUpdate, ...] = ()
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
        if len(self.activities) > MAX_ACTIVITY_COUNT:
            raise ValueError("OutboundResponse.activities exceeds cap")
        activity_chars = sum(_activity_chars(activity) for activity in self.activities)
        if activity_chars > MAX_ACTIVITY_TOTAL_CHARS:
            raise ValueError(
                "OutboundResponse.activities exceeds character budget "
                f"({activity_chars} > {MAX_ACTIVITY_TOTAL_CHARS})"
            )
        if len(self.stream_chunks) > MAX_STREAM_CHUNKS:
            raise ValueError("OutboundResponse.stream_chunks exceeds cap")
        if any(not chunk or not chunk.strip() for chunk in self.stream_chunks):
            raise ValueError("OutboundResponse.stream_chunks MUST be non-empty")
        if sum(len(chunk) for chunk in self.stream_chunks) > MAX_TEXT_CHARS:
            raise ValueError("OutboundResponse.stream_chunks exceeds text cap")
        if len(self.progress_updates) > MAX_PROGRESS_UPDATES:
            raise ValueError("OutboundResponse.progress_updates exceeds cap")
        if self.progress_updates:
            if tuple(update.revision for update in self.progress_updates) != tuple(
                range(len(self.progress_updates))
            ):
                raise ValueError("OutboundResponse progress revisions MUST be contiguous")
            if any(
                current.activity_count > following.activity_count
                for current, following in zip(
                    self.progress_updates,
                    self.progress_updates[1:],
                    strict=False,
                )
            ):
                raise ValueError("OutboundResponse progress activity counts MUST be monotonic")
            if any(
                update.status is not ChannelProgressStatus.RUNNING
                for update in self.progress_updates[:-1]
            ):
                raise ValueError("only the final channel progress update can be confirmed")
            final_update = self.progress_updates[-1]
            if (
                final_update.status is not ChannelProgressStatus.CONFIRMED
                or final_update.text != self.text
                or final_update.activity_count != len(self.activities)
            ):
                raise ValueError("final channel progress update MUST match the canonical response")
        if self.edit_message_id is not None:
            _bounded("edit_message_id", self.edit_message_id, MAX_MESSAGE_ID_CHARS)
        if self.reaction is not None:
            _bounded("reaction", self.reaction, 64)
            if self.mentions or self.activities:
                raise ValueError("OutboundResponse reactions cannot carry mentions or activities")
        if self.thread_mode is ChannelThreadMode.DEDICATED and self.thread_id is not None:
            raise ValueError("dedicated thread delivery cannot declare an existing thread_id")
        rich_modes = sum(
            (
                bool(self.stream_chunks),
                bool(self.progress_updates),
                self.edit_message_id is not None,
                self.reaction is not None,
            )
        )
        if rich_modes > 1:
            raise ValueError("OutboundResponse rich delivery modes are mutually exclusive")

    @property
    def operation(self) -> ChannelDeliveryOperation:
        if self.stream_chunks or self.progress_updates:
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
        "activities": [_activity_to_json(activity) for activity in response.activities],
        "stream_chunks": list(response.stream_chunks),
        "progress_updates": [
            {
                "revision": update.revision,
                "status": update.status.value,
                "text": update.text,
                "activity_count": update.activity_count,
            }
            for update in response.progress_updates
        ],
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
    activities = value.get("activities", [])
    if not isinstance(activities, list):
        raise ValueError("stored outbound response activities MUST be objects")
    progress_updates = value.get("progress_updates", [])
    if not isinstance(progress_updates, list) or any(
        not isinstance(item, Mapping) for item in progress_updates
    ):
        raise ValueError("stored outbound response progress_updates MUST be objects")
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
        activities=tuple(_activity_from_json(item) for item in activities),
        stream_chunks=tuple(str(item) for item in value.get("stream_chunks", ())),
        progress_updates=tuple(
            _progress_update_from_json(item)
            for item in cast(list[Mapping[str, object]], progress_updates)
        ),
        edit_message_id=(
            str(value["edit_message_id"]) if value.get("edit_message_id") is not None else None
        ),
        reaction=str(value["reaction"]) if value.get("reaction") is not None else None,
        thread_mode=ChannelThreadMode(str(value.get("thread_mode", "origin"))),
    )


def _progress_update_from_json(value: Mapping[str, object]) -> ChannelProgressUpdate:
    revision = value.get("revision")
    activity_count = value.get("activity_count")
    text = value.get("text")
    status = value.get("status")
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or not isinstance(activity_count, int)
        or isinstance(activity_count, bool)
        or not isinstance(text, str)
        or not isinstance(status, str)
    ):
        raise ValueError("stored channel progress update has invalid scalar types")
    return ChannelProgressUpdate(
        revision=revision,
        status=ChannelProgressStatus(status),
        text=text,
        activity_count=activity_count,
    )


def _bounded(name: str, value: str, maximum: int) -> None:
    if not value or not value.strip():
        raise ValueError(f"InboundTurn.{name} MUST be non-empty")
    if len(value) > maximum:
        raise ValueError(f"InboundTurn.{name} exceeds cap ({len(value)} > {maximum})")


def _safe_bounded(name: str, value: str, maximum: int) -> None:
    _bounded(name, value, maximum)
    if _SENSITIVE_ACTIVITY_TEXT.search(value):
        raise ValueError(f"{name} contains sensitive channel content")


def _rfc3339(name: str, value: str) -> datetime:
    if _RFC3339.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(
            value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
        )
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} MUST include a timezone")
    return parsed


def _activity_chars(activity: ConversationActivity) -> int:
    if isinstance(activity, AgentHandoffActivity):
        return sum(
            len(value)
            for value in (
                activity.from_agent,
                activity.to_agent,
                activity.task,
                activity.trace_ref or "",
            )
        )
    return sum(
        len(value)
        for value in (
            activity.agent,
            activity.label,
            activity.tool,
            activity.command,
            activity.output,
            activity.started_at or "",
            activity.completed_at or "",
            activity.authority or "",
        )
    )


def _activity_to_json(activity: ConversationActivity) -> dict[str, Any]:
    if isinstance(activity, AgentHandoffActivity):
        return {
            "kind": "handoff",
            "from_agent": activity.from_agent,
            "to_agent": activity.to_agent,
            "task": activity.task,
            "trace_ref": activity.trace_ref,
        }
    return {
        "kind": "execution",
        "agent": activity.agent,
        "label": activity.label,
        "tool": activity.tool,
        "command": activity.command,
        "status": activity.status.value,
        "redacted": activity.redacted,
        "output": activity.output,
        "output_truncated": activity.output_truncated,
        "exit_code": activity.exit_code,
        "started_at": activity.started_at,
        "completed_at": activity.completed_at,
        "duration_ms": activity.duration_ms,
        "authority": activity.authority,
    }


def _activity_from_json(value: object) -> ConversationActivity:
    if not isinstance(value, Mapping):
        raise ValueError("stored conversation activity MUST be an object")
    if value.get("kind") == "handoff":
        return AgentHandoffActivity(
            from_agent=_required_json_text(value, "from_agent"),
            to_agent=_required_json_text(value, "to_agent"),
            task=_required_json_text(value, "task"),
            trace_ref=_optional_json_text(value, "trace_ref"),
        )
    if value.get("kind") != "execution":
        raise ValueError("stored conversation activity kind is unsupported")
    return ObservedExecutionActivity(
        agent=_required_json_text(value, "agent"),
        label=_required_json_text(value, "label"),
        tool=_required_json_text(value, "tool"),
        command=_required_json_text(value, "command"),
        status=ConversationExecutionStatus(_required_json_text(value, "status")),
        redacted=_required_json_true(value, "redacted"),
        output=_optional_json_text(value, "output") or "",
        output_truncated=_optional_json_bool(value, "output_truncated"),
        exit_code=_optional_json_int(value, "exit_code"),
        started_at=_optional_json_text(value, "started_at"),
        completed_at=_optional_json_text(value, "completed_at"),
        duration_ms=_optional_json_int(value, "duration_ms"),
        authority=_optional_json_text(value, "authority"),
    )


def _required_json_text(value: Mapping[object, object], field_name: str) -> str:
    raw = value.get(field_name)
    if not isinstance(raw, str):
        raise ValueError(f"stored conversation activity {field_name} MUST be a string")
    return raw


def _optional_json_text(value: Mapping[object, object], field_name: str) -> str | None:
    raw = value.get(field_name)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"stored conversation activity {field_name} MUST be a string")
    return raw


def _optional_json_bool(value: Mapping[object, object], field_name: str) -> bool:
    if field_name not in value:
        return False
    raw = value[field_name]
    if not isinstance(raw, bool):
        raise ValueError(f"stored conversation activity {field_name} MUST be a boolean")
    return raw


def _optional_json_int(value: Mapping[object, object], field_name: str) -> int | None:
    raw = value.get(field_name)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"stored conversation activity {field_name} MUST be an integer")
    return raw


def _required_json_true(value: Mapping[object, object], field_name: str) -> Literal[True]:
    if value.get(field_name) is not True:
        raise ValueError(f"stored conversation activity {field_name} MUST be true")
    return True


__all__ = [
    "AgentHandoffActivity",
    "ChannelAttachment",
    "ChannelDeliveryOperation",
    "ChannelDeliveryError",
    "ChannelDeliveryReceipt",
    "ChannelMention",
    "ChannelProgressStatus",
    "ChannelProgressUpdate",
    "ChannelThreadMode",
    "ConversationChannelAdapter",
    "ConversationChannelKind",
    "ConversationActivity",
    "ConversationExecutionStatus",
    "InboundTurn",
    "MAX_ATTACHMENT_COUNT",
    "MAX_ACTIVITY_COUNT",
    "MAX_ACTIVITY_TOTAL_CHARS",
    "MAX_MENTION_COUNT",
    "MAX_PROGRESS_UPDATES",
    "MAX_STREAM_CHUNKS",
    "OutboundResponse",
    "ObservedExecutionActivity",
    "outbound_response_from_json",
    "outbound_response_to_json",
]
