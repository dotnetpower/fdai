"""Legal-hold-aware physical retention for expired scheduled continuations.

Expiry only removes resolution authority. This worker performs the coordinated physical
deletion of the source result, the anchor, and the projected conversation turn so that
"expired" can be reported as completed deletion. It fails closed on an active anchor, a
legal hold, an unreadable hold registry, or any partial deleter failure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from fdai.shared.providers.scheduled_continuation import (
    ContinuationAnchorState,
    ScheduledConversationAnchor,
    ScheduledConversationAnchorStore,
)
from fdai.shared.providers.state_store import StateStore

MAX_RETENTION_BATCH = 100
RETENTION_WORKER_PRINCIPAL = "system:scheduled-continuation-retention"


class RetentionTarget(StrEnum):
    """Deletion order. The anchor is removed last so a failure stays resumable."""

    PROJECTED_TURN = "projected_turn"
    SOURCE_RESULT = "source_result"
    ANCHOR = "anchor"


RETENTION_ORDER: tuple[RetentionTarget, ...] = (
    RetentionTarget.PROJECTED_TURN,
    RetentionTarget.SOURCE_RESULT,
    RetentionTarget.ANCHOR,
)


class RetentionOutcome(StrEnum):
    PURGED = "purged"
    HELD = "held"
    NOT_DUE = "not_due"
    PARTIAL = "partial"


class RetentionHoldUnavailableError(RuntimeError):
    """The legal-hold registry could not be read, so deletion MUST NOT proceed."""


class RetentionNotExpiredError(RuntimeError):
    """An active anchor is never physically deleted."""


@dataclass(frozen=True, slots=True)
class RetentionAuditEvent:
    outcome: RetentionOutcome
    anchor_id: str
    completed_targets: tuple[RetentionTarget, ...]
    at: datetime

    @property
    def idempotency_key(self) -> str:
        completed = ",".join(target.value for target in self.completed_targets)
        return f"scheduled-continuation:retention:{self.outcome.value}:{self.anchor_id}:{completed}"


@dataclass(frozen=True, slots=True)
class RetentionResult:
    anchor_id: str
    outcome: RetentionOutcome
    completed_targets: tuple[RetentionTarget, ...]
    failed_target: RetentionTarget | None = None

    @property
    def deleted(self) -> bool:
        return self.outcome is RetentionOutcome.PURGED


class LegalHoldRegistry(Protocol):
    """Authoritative hold state. A read failure MUST raise, never return False."""

    async def is_held(self, *, anchor_id: str) -> bool: ...


class RetentionDeleter(Protocol):
    """Physically delete one target. Deleting an absent target is a successful no-op."""

    async def delete(
        self, *, target: RetentionTarget, anchor: ScheduledConversationAnchor
    ) -> None: ...


class RetentionAuditSink(Protocol):
    async def append(self, event: RetentionAuditEvent) -> None: ...


class InMemoryLegalHoldRegistry:
    def __init__(self, held_anchor_ids: Sequence[str] = ()) -> None:
        self._held = set(held_anchor_ids)

    def place_hold(self, anchor_id: str) -> None:
        self._held.add(anchor_id)

    def release_hold(self, anchor_id: str) -> None:
        self._held.discard(anchor_id)

    async def is_held(self, *, anchor_id: str) -> bool:
        return anchor_id in self._held


class InMemoryRetentionAuditSink:
    def __init__(self) -> None:
        self.events: list[RetentionAuditEvent] = []
        self._seen: set[str] = set()

    async def append(self, event: RetentionAuditEvent) -> None:
        if event.idempotency_key in self._seen:
            return
        self._seen.add(event.idempotency_key)
        self.events.append(event)


class StateStoreRetentionAuditSink:
    """Append retention decisions to the existing hash-chained audit log."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def append(self, event: RetentionAuditEvent) -> None:
        await self._store.write_state_with_audit_if_absent(
            f"scheduled-continuation:retention:{event.idempotency_key}",
            {"recorded": True},
            {
                "event_type": f"scheduled_continuation.retention.{event.outcome.value}",
                "anchor_id": event.anchor_id,
                "principal_id": RETENTION_WORKER_PRINCIPAL,
                "completed_targets": [target.value for target in event.completed_targets],
                "recorded_at": event.at.isoformat(),
                "idempotency_key": event.idempotency_key,
            },
        )


class ScheduledContinuationRetentionWorker:
    """Coordinate physical deletion of one expired, hold-free continuation."""

    def __init__(
        self,
        *,
        store: ScheduledConversationAnchorStore,
        holds: LegalHoldRegistry,
        deleter: RetentionDeleter,
        audit: RetentionAuditSink,
        grace: timedelta = timedelta(days=30),
    ) -> None:
        if grace < timedelta(0):
            raise ValueError("grace MUST NOT be negative")
        self._store = store
        self._holds = holds
        self._deleter = deleter
        self._audit = audit
        self._grace = grace

    async def purge(self, *, anchor_id: str, now: datetime) -> RetentionResult:
        if now.tzinfo is None:
            raise ValueError("now MUST be timezone-aware")
        anchor = await self._store.get(anchor_id)
        if anchor is None:
            # Already physically deleted, or never existed. Reveal neither.
            return RetentionResult(
                anchor_id=anchor_id,
                outcome=RetentionOutcome.PURGED,
                completed_targets=RETENTION_ORDER,
            )
        if anchor.state is not ContinuationAnchorState.EXPIRED:
            raise RetentionNotExpiredError("an active continuation anchor is never deleted")
        if now < anchor.expires_at + self._grace:
            return await self._record(anchor, RetentionOutcome.NOT_DUE, (), now)
        try:
            held = await self._holds.is_held(anchor_id=anchor.anchor_id)
        except Exception as error:  # noqa: BLE001 - fail closed on any registry failure
            raise RetentionHoldUnavailableError(
                "legal-hold state is unavailable; retention MUST NOT delete"
            ) from error
        if held:
            return await self._record(anchor, RetentionOutcome.HELD, (), now)

        completed: list[RetentionTarget] = []
        for target in RETENTION_ORDER:
            try:
                await self._deleter.delete(target=target, anchor=anchor)
            except Exception:  # noqa: BLE001 - a partial failure stays resumable
                await self._record(anchor, RetentionOutcome.PARTIAL, tuple(completed), now)
                return RetentionResult(
                    anchor_id=anchor.anchor_id,
                    outcome=RetentionOutcome.PARTIAL,
                    completed_targets=tuple(completed),
                    failed_target=target,
                )
            completed.append(target)
        return await self._record(anchor, RetentionOutcome.PURGED, tuple(completed), now)

    async def purge_batch(
        self, *, anchor_ids: Sequence[str], now: datetime
    ) -> tuple[RetentionResult, ...]:
        if len(anchor_ids) > MAX_RETENTION_BATCH:
            raise ValueError(f"batch MUST NOT exceed {MAX_RETENTION_BATCH} anchors")
        results: list[RetentionResult] = []
        for anchor_id in anchor_ids:
            results.append(await self.purge(anchor_id=anchor_id, now=now))
        return tuple(results)

    async def _record(
        self,
        anchor: ScheduledConversationAnchor,
        outcome: RetentionOutcome,
        completed: tuple[RetentionTarget, ...],
        now: datetime,
    ) -> RetentionResult:
        await self._audit.append(
            RetentionAuditEvent(
                outcome=outcome,
                anchor_id=anchor.anchor_id,
                completed_targets=completed,
                at=now,
            )
        )
        return RetentionResult(
            anchor_id=anchor.anchor_id,
            outcome=outcome,
            completed_targets=completed,
        )


__all__ = [
    "MAX_RETENTION_BATCH",
    "RETENTION_ORDER",
    "RETENTION_WORKER_PRINCIPAL",
    "InMemoryLegalHoldRegistry",
    "InMemoryRetentionAuditSink",
    "LegalHoldRegistry",
    "RetentionAuditEvent",
    "RetentionAuditSink",
    "RetentionDeleter",
    "RetentionHoldUnavailableError",
    "RetentionNotExpiredError",
    "RetentionOutcome",
    "RetentionResult",
    "RetentionTarget",
    "ScheduledContinuationRetentionWorker",
    "StateStoreRetentionAuditSink",
]
