"""Transport-neutral outcomes for one-shot conversation execution."""

from __future__ import annotations

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


class JsonTurnExecutionError(RuntimeError):
    """Typed application failure mapped to HTTP only by the route adapter."""

    def __init__(self, *, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
