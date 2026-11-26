"""Deterministic channel-neutral arbitration for follow-ups to a busy session."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

_MAX_TEXT_BYTES = 4_000
_MAX_PENDING = 32
_MAX_PENDING_BYTES = 32_000


class BusyInputMode(StrEnum):
    QUEUE = "queue"
    INTERRUPT = "interrupt"
    STEER = "steer"


class BusyInputKind(StrEnum):
    PROSE = "prose"
    APPROVAL = "approval"
    DENIAL = "denial"
    EMERGENCY_STOP = "emergency_stop"


class BusyInputDisposition(StrEnum):
    QUEUED = "queued"
    INTERRUPTING = "interrupting"
    STEERED = "steered"
    REJECTED = "rejected"


class BusyPendingStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class BusyInput:
    input_id: str
    idempotency_key: str
    session_id: str
    principal_id: str
    content: str
    kind: BusyInputKind
    received_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("input_id", self.input_id),
            ("idempotency_key", self.idempotency_key),
            ("session_id", self.session_id),
            ("principal_id", self.principal_id),
        ):
            _identifier(name, value)
        if not self.content.strip() or len(self.content.encode()) > _MAX_TEXT_BYTES:
            raise ValueError("busy input content MUST be bounded and non-empty")
        _aware("received_at", self.received_at)
        _aware("expires_at", self.expires_at)
        if self.expires_at <= self.received_at:
            raise ValueError("busy input expires_at MUST be after received_at")


@dataclass(frozen=True, slots=True)
class PendingBusyInput:
    input: BusyInput
    sequence: int
    disposition: BusyInputDisposition
    status: BusyPendingStatus = BusyPendingStatus.PENDING
    consumed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("busy input sequence MUST be non-negative")
        if self.disposition is BusyInputDisposition.REJECTED:
            if self.status is not BusyPendingStatus.REJECTED:
                raise ValueError("rejected disposition requires rejected status")
        elif self.status is BusyPendingStatus.REJECTED:
            raise ValueError("rejected status requires rejected disposition")
        if self.status is BusyPendingStatus.CONSUMED and self.consumed_at is None:
            raise ValueError("consumed input requires consumed_at")
        if self.consumed_at is not None:
            _aware("consumed_at", self.consumed_at)


@dataclass(frozen=True, slots=True)
class BusySessionState:
    session_id: str
    owner_principal_id: str
    mode: BusyInputMode
    revision: int
    next_sequence: int
    active_turn_id: str | None = None
    pending: tuple[PendingBusyInput, ...] = ()

    def __post_init__(self) -> None:
        _identifier("session_id", self.session_id)
        _identifier("owner_principal_id", self.owner_principal_id)
        if self.active_turn_id is not None:
            _identifier("active_turn_id", self.active_turn_id)
        if self.revision < 1 or self.next_sequence < 0:
            raise ValueError("busy session revision and sequence are invalid")
        if len(self.pending) > _MAX_PENDING:
            raise ValueError("busy session pending input cap exceeded")
        sequences = [item.sequence for item in self.pending]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("busy session pending sequences MUST be unique and ordered")


@dataclass(frozen=True, slots=True)
class BusyInputDecision:
    state: BusySessionState
    record: PendingBusyInput
    duplicate: bool = False
    reason: str | None = None


def arbitrate_busy_input(
    state: BusySessionState,
    incoming: BusyInput,
    *,
    now: datetime,
) -> BusyInputDecision:
    """Give one input one durable disposition without dropping prior inputs."""

    _aware("now", now)
    if incoming.session_id != state.session_id or incoming.principal_id != state.owner_principal_id:
        return _rejected(state, incoming, "authorization_mismatch")
    duplicate = next(
        (item for item in state.pending if item.input.idempotency_key == incoming.idempotency_key),
        None,
    )
    if duplicate is not None:
        return BusyInputDecision(state=state, record=duplicate, duplicate=True)
    if incoming.expires_at <= now:
        return _rejected(state, incoming, "input_expired")
    if incoming.kind is not BusyInputKind.PROSE and state.mode is BusyInputMode.STEER:
        return _rejected(state, incoming, "control_input_cannot_steer")
    pending_items = [item for item in state.pending if item.status is BusyPendingStatus.PENDING]
    pending_bytes = sum(len(item.input.content.encode()) for item in pending_items)
    if (
        len(pending_items) >= _MAX_PENDING
        or pending_bytes + len(incoming.content.encode()) > _MAX_PENDING_BYTES
    ):
        return _rejected(state, incoming, "queue_capacity_exceeded")
    if incoming.kind is not BusyInputKind.PROSE:
        disposition = BusyInputDisposition.QUEUED
    elif state.active_turn_id is None or state.mode is BusyInputMode.QUEUE:
        disposition = BusyInputDisposition.QUEUED
    elif state.mode is BusyInputMode.INTERRUPT:
        disposition = BusyInputDisposition.INTERRUPTING
    else:
        disposition = BusyInputDisposition.STEERED
    record = PendingBusyInput(
        input=incoming,
        sequence=state.next_sequence,
        disposition=disposition,
    )
    updated = replace(
        state,
        revision=state.revision + 1,
        next_sequence=state.next_sequence + 1,
        pending=(*state.pending, record),
    )
    return BusyInputDecision(state=updated, record=record)


def finish_active_turn(
    state: BusySessionState,
    *,
    turn_id: str,
) -> BusySessionState:
    """Close one turn and preserve unconsumed steer as queued work."""

    if state.active_turn_id != turn_id:
        raise ValueError("active turn mismatch")
    pending = tuple(
        replace(item, disposition=BusyInputDisposition.QUEUED)
        if item.status is BusyPendingStatus.PENDING
        and item.disposition is BusyInputDisposition.STEERED
        else item
        for item in state.pending
    )
    return replace(
        state,
        active_turn_id=None,
        revision=state.revision + 1,
        pending=pending,
    )


def consume_pending_input(
    state: BusySessionState,
    *,
    sequence: int,
    principal_id: str,
    at: datetime,
) -> tuple[BusySessionState, PendingBusyInput]:
    """Consume exactly once after rechecking the current principal."""

    if principal_id != state.owner_principal_id:
        raise PermissionError("busy input consumption principal mismatch")
    _aware("at", at)
    selected: PendingBusyInput | None = None
    updated_items: list[PendingBusyInput] = []
    for item in state.pending:
        if item.sequence != sequence:
            updated_items.append(item)
            continue
        if item.status is not BusyPendingStatus.PENDING:
            raise ValueError("busy input is not pending")
        selected = replace(item, status=BusyPendingStatus.CONSUMED, consumed_at=at)
        updated_items.append(selected)
    if selected is None:
        raise LookupError(f"busy input sequence {sequence} was not found")
    return (
        replace(state, revision=state.revision + 1, pending=tuple(updated_items)),
        selected,
    )


def _rejected(state: BusySessionState, incoming: BusyInput, reason: str) -> BusyInputDecision:
    record = PendingBusyInput(
        input=incoming,
        sequence=state.next_sequence,
        disposition=BusyInputDisposition.REJECTED,
        status=BusyPendingStatus.REJECTED,
    )
    return BusyInputDecision(state=state, record=record, reason=reason)


def _identifier(name: str, value: str) -> None:
    if not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "BusyInput",
    "BusyInputDecision",
    "BusyInputDisposition",
    "BusyInputKind",
    "BusyInputMode",
    "BusyPendingStatus",
    "BusySessionState",
    "PendingBusyInput",
    "arbitrate_busy_input",
    "consume_pending_input",
    "finish_active_turn",
]
