"""Transport-neutral outcomes for one-shot conversation execution."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class JsonTurnOutcome(StrEnum):
    """Application outcomes that the HTTP adapter maps to response statuses."""

    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class JsonTurnExecutionResult:
    """One application-owned payload plus its transport-neutral outcome."""

    payload: dict[str, Any]
    outcome: JsonTurnOutcome = JsonTurnOutcome.COMPLETED


@dataclass(frozen=True, slots=True)
class StreamTurnEvent:
    """One semantic event with its application-owned canonical answer revision.

    The HTTP adapter adds a separate monotonic ``seq`` for wire-frame order. It
    preserves ``revision`` unchanged so retries and confirmed corrections cannot
    be reinterpreted as transport sequence changes.
    """

    event: str | None
    payload: dict[str, Any] | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class StreamTurnExecution:
    """Single-use semantic event stream prepared before HTTP delivery starts."""

    request_id: str
    events: AsyncIterator[StreamTurnEvent]
    recover_transport_error: Callable[[BaseException], Awaitable[StreamTurnEvent | None]]


class StreamTurnExecutionError(RuntimeError):
    """Typed pre-stream failure mapped to HTTP only by the route adapter."""

    def __init__(self, *, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class JsonTurnExecutionError(RuntimeError):
    """Typed application failure mapped to HTTP only by the route adapter."""

    def __init__(self, *, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
