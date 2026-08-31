"""Sanitized two-phase audit contract for human approval callbacks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class HilCallbackAuditPhase(StrEnum):
    """Durable phases written around callback validation and recording."""

    PREPARED = "prepared"
    COMPLETED = "completed"


class HilCallbackOutcome(StrEnum):
    """Sanitized terminal callback outcomes."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class HilCallbackAuditRecord:
    """One content-free callback audit phase."""

    callback_id: str
    phase: HilCallbackAuditPhase
    correlation_id: str
    actor_identity_ref: str
    authority_basis: str
    outcome: HilCallbackOutcome
    recorded_at: datetime

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.callback_id,
                self.correlation_id,
                self.actor_identity_ref,
                self.authority_basis,
            )
        ):
            raise ValueError("HIL callback audit identity fields MUST be non-empty")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("HIL callback audit time MUST be timezone-aware")


class HilCallbackAuditWriter(Protocol):
    """Persist append-only callback audit phases without provider content."""

    async def append_callback_audit(self, record: HilCallbackAuditRecord) -> None: ...


def actor_identity_reference(value: str | None) -> str:
    """Return a stable non-reversible reference for an actor identity."""
    normalized = (value or "unresolved").strip().casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


__all__ = [
    "HilCallbackAuditPhase",
    "HilCallbackAuditRecord",
    "HilCallbackAuditWriter",
    "HilCallbackOutcome",
    "actor_identity_reference",
]
