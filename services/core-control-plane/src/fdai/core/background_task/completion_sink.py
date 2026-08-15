"""Completion sink that hands a terminal background result to the user.

The sink never reruns the investigation. It reads the immutable terminal result
of one attempt, appends a deterministic provenance-labeled conversation turn,
and submits the same immutable reply through the durable delivery ledger.

Every identifier is derived from the attempt, so a replay after an ambiguous
failure reuses the same turn and the same delivery record instead of producing
a second answer.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.background_task.models import (
    TERMINAL_BACKGROUND_STATUSES,
    BackgroundTaskAttempt,
)
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    OutboundDeliveryRecord,
    new_delivery_record,
)

RESULT_LABEL = "[Background task result: {terminal_reason}]"
DEFAULT_FRESHNESS = timedelta(hours=1)
DEFAULT_RETENTION = timedelta(days=30)


class CompletionSinkError(RuntimeError):
    """Raised when a completion cannot become a user-visible reply."""


@dataclass(frozen=True, slots=True)
class BackgroundTaskTurn:
    """Deterministic conversation turn appended for one terminal attempt."""

    turn_id: str
    idempotency_key: str
    conversation_id: str
    principal_id: str
    correlation_id: str
    attempt_id: str
    task_id: str
    text: str
    evidence_refs: tuple[str, ...]
    terminal_reason: str
    trusted: bool = False

    def __post_init__(self) -> None:
        if self.trusted:
            raise ValueError("background task turns MUST remain untrusted")


class ConversationTurnAppender(Protocol):
    """Idempotent conversation history sink keyed by `turn_id`."""

    async def append(self, turn: BackgroundTaskTurn) -> None: ...


class DeliverySubmitter(Protocol):
    """Durable delivery ledger write keyed by the delivery idempotency key."""

    async def put(self, record: OutboundDeliveryRecord) -> OutboundDeliveryRecord: ...


@dataclass(frozen=True, slots=True)
class ConversationCompletionSink:
    """Append the deterministic turn and submit the immutable reply once."""

    appender: ConversationTurnAppender
    deliveries: DeliverySubmitter
    scope_ref: str
    binding_id: str | None = None
    freshness: timedelta = DEFAULT_FRESHNESS
    retention: timedelta = DEFAULT_RETENTION
    clock: Callable[[], datetime] | None = None

    async def publish(self, attempt: BackgroundTaskAttempt) -> None:
        turn = build_turn(attempt)
        await self.appender.append(turn)
        now = (self.clock or _utc_now)()
        response = OutboundResponse(
            channel_kind=_channel_kind(attempt.task.origin.channel_kind),
            channel_id=attempt.task.origin.channel_id,
            in_reply_to=attempt.task.origin.message_id or attempt.task.task_id,
            thread_id=attempt.task.origin.thread_id,
            status=attempt.status.value,
            text=turn.text,
            evidence_refs=turn.evidence_refs,
        )
        await self.deliveries.put(
            new_delivery_record(
                origin_ref=completion_origin_ref(attempt),
                principal_id=attempt.task.owner_principal_id,
                scope_ref=self.scope_ref,
                conversation_id=attempt.task.origin.conversation_id,
                binding_id=self.binding_id,
                response=response,
                created_at=now,
                freshness=self.freshness,
                retention=self.retention,
            )
        )


def completion_origin_ref(attempt: BackgroundTaskAttempt) -> str:
    """Return the stable delivery origin for one terminal attempt."""

    return f"background-task:{attempt.attempt_id}"


def build_turn(attempt: BackgroundTaskAttempt) -> BackgroundTaskTurn:
    """Render the deterministic, provenance-labeled turn for one attempt."""

    if attempt.status not in TERMINAL_BACKGROUND_STATUSES:
        raise CompletionSinkError("only a terminal attempt can produce a completion turn")
    result = attempt.result
    if result is None:  # pragma: no cover - model invariant
        raise CompletionSinkError("a terminal attempt MUST carry an immutable result")
    if result.trusted:  # pragma: no cover - model invariant
        raise CompletionSinkError("background task results MUST remain untrusted")
    label = RESULT_LABEL.format(terminal_reason=result.terminal_reason)
    summary = (result.summary or "").strip()
    text = f"{label}\n{summary}" if summary else label
    key = _deterministic_key(attempt)
    return BackgroundTaskTurn(
        turn_id=f"turn:{key}",
        idempotency_key=key,
        conversation_id=attempt.task.origin.conversation_id,
        principal_id=attempt.task.owner_principal_id,
        correlation_id=attempt.task.correlation_id,
        attempt_id=attempt.attempt_id,
        task_id=attempt.task.task_id,
        text=text,
        evidence_refs=result.evidence_refs,
        terminal_reason=result.terminal_reason,
    )


def _deterministic_key(attempt: BackgroundTaskAttempt) -> str:
    digest = hashlib.sha256()
    for part in (attempt.task.task_id, attempt.attempt_id, str(attempt.attempt_number)):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def _channel_kind(value: str) -> ConversationChannelKind:
    try:
        return ConversationChannelKind(value)
    except ValueError as exc:
        raise CompletionSinkError(f"unsupported origin channel kind: {value}") from exc


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "RESULT_LABEL",
    "BackgroundTaskTurn",
    "CompletionSinkError",
    "ConversationCompletionSink",
    "ConversationTurnAppender",
    "DeliverySubmitter",
    "build_turn",
    "completion_origin_ref",
]
