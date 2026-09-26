"""Legal-hold-aware physical retention for expired scheduled continuations.

Expiry only removes resolution authority. This worker performs the coordinated physical
deletion of the source result, the anchor, and the projected conversation turn so that
"expired" can be reported as completed deletion. It fails closed on an active anchor, a
legal hold, an unreadable hold registry, an unavailable deletion fence, or any partial
deleter failure. The fence is recorded before the first deletion, so a late writer cannot
restore a body that this worker started to delete.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
MAX_FENCE_MIGRATION_BATCH = 100
MAX_FENCE_ALIASES = 8
RETENTION_WORKER_PRINCIPAL = "system:scheduled-continuation-retention"
DELETION_FENCE_PREFIX = "scheduled-continuation:deleted:"


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


class RetentionFenceUnavailableError(RuntimeError):
    """The deletion fence could not be recorded or read, so deletion MUST NOT proceed."""


class ContinuationDeletionFencedError(RuntimeError):
    """A fenced anchor id MUST NOT be recreated or replayed after deletion."""


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


class ContinuationDeletionFence(Protocol):
    """Durable tombstone that blocks a late writer from restoring a deleted body.

    The fence is recorded before the first deletion, so a replay, queue redelivery, or
    recreated anchor that arrives during or after the purge is refused. A read or write
    failure MUST raise instead of reporting an absent fence.
    """

    async def record(self, *, anchor_id: str, at: datetime) -> None: ...

    async def is_fenced(self, *, anchor_id: str) -> bool: ...


class InMemoryContinuationDeletionFence:
    """Process-local fence. Production composition MUST inject a durable fence."""

    def __init__(self, fenced_anchor_ids: Sequence[str] = ()) -> None:
        self._fenced = set(fenced_anchor_ids)

    async def record(self, *, anchor_id: str, at: datetime) -> None:
        del at
        self._fenced.add(anchor_id)

    async def is_fenced(self, *, anchor_id: str) -> bool:
        return anchor_id in self._fenced


class StateStoreContinuationDeletionFence:
    """Persist the fence and its non-sensitive audit lineage in the shared StateStore.

    The fence record carries the anchor id, the recording principal, and the time. It
    never carries the deleted result body, so lineage survives without the payload.

    The fence is permanent. `DELETION_FENCE_PREFIX` MUST NOT be subject to any
    prefix retention such as `delete_states_beyond`, because a pruned fence would let a
    replayed run recreate a deleted body.
    """

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def record(self, *, anchor_id: str, at: datetime) -> None:
        await self._store.write_state_with_audit_if_absent(
            f"{DELETION_FENCE_PREFIX}{anchor_id}",
            {"fenced": True, "recorded_at": at.isoformat()},
            {
                "event_type": "scheduled_continuation.retention.fenced",
                "anchor_id": anchor_id,
                "principal_id": RETENTION_WORKER_PRINCIPAL,
                "recorded_at": at.isoformat(),
                "idempotency_key": f"{DELETION_FENCE_PREFIX}{anchor_id}",
            },
        )

    async def is_fenced(self, *, anchor_id: str) -> bool:
        return await self._store.read_state(f"{DELETION_FENCE_PREFIX}{anchor_id}") is not None


class LegacyAliasDeletionFence:
    """Read a tombstone under the current anchor id and its superseded derivations.

    A change to the anchor id derivation moves the fence key, so a recreated run could
    otherwise be accepted under its new id while its tombstone stays at the old key. This
    decorator resolves a bounded set of superseded ids for the current id and refuses the
    recreated id before `ContinuationFenceMigrator` has carried the tombstone forward.
    Writes always use the current derivation, so new tombstones never grow the alias set.
    """

    def __init__(
        self,
        *,
        fence: ContinuationDeletionFence,
        aliases: Mapping[str, Sequence[str]],
    ) -> None:
        resolved: dict[str, tuple[str, ...]] = {}
        for current_anchor_id, legacy_anchor_ids in aliases.items():
            _fence_identifier("current_anchor_id", current_anchor_id)
            legacy = tuple(dict.fromkeys(legacy_anchor_ids))
            if len(legacy) > MAX_FENCE_ALIASES:
                raise ValueError(f"alias set MUST NOT exceed {MAX_FENCE_ALIASES} anchor ids")
            for legacy_anchor_id in legacy:
                _fence_identifier("legacy_anchor_id", legacy_anchor_id)
                if legacy_anchor_id == current_anchor_id:
                    raise ValueError("an alias MUST differ from the current anchor id")
            resolved[current_anchor_id] = legacy
        owners: dict[str, str] = {}
        for current_anchor_id, legacy_anchor_ids in resolved.items():
            for legacy_anchor_id in legacy_anchor_ids:
                if legacy_anchor_id in resolved or legacy_anchor_id in owners:
                    raise ValueError("a legacy anchor id MUST belong to only one current anchor id")
                owners[legacy_anchor_id] = current_anchor_id
        self._fence = fence
        self._aliases = resolved

    async def record(self, *, anchor_id: str, at: datetime) -> None:
        await self._fence.record(anchor_id=anchor_id, at=at)

    async def is_fenced(self, *, anchor_id: str) -> bool:
        if await self._fence.is_fenced(anchor_id=anchor_id):
            return True
        for legacy_anchor_id in self._aliases.get(anchor_id, ()):
            if await self._fence.is_fenced(anchor_id=legacy_anchor_id):
                return True
        return False


@dataclass(frozen=True, slots=True)
class FenceCarryForward:
    """One superseded tombstone key and the current derivation that replaces it."""

    legacy_anchor_id: str
    current_anchor_id: str

    def __post_init__(self) -> None:
        _fence_identifier("legacy_anchor_id", self.legacy_anchor_id)
        _fence_identifier("current_anchor_id", self.current_anchor_id)
        if self.legacy_anchor_id == self.current_anchor_id:
            raise ValueError("carry-forward MUST cross two anchor id derivations")


@dataclass(frozen=True, slots=True)
class FenceMigrationResult:
    """Bounded, resumable outcome of one tombstone carry-forward batch."""

    carried: tuple[str, ...]
    already_present: tuple[str, ...]
    absent: tuple[str, ...]
    pending: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.pending == ()


class ContinuationFenceMigrator:
    """Carry superseded deletion tombstones forward to the current anchor id derivation.

    The migration is bounded, idempotent, and resumable: a carried tombstone is observed as
    already present on the next run, and a write that does not survive its own readback
    stays pending instead of being reported as migrated. The legacy tombstone is never
    removed, because it remains the permanent record for the old key.
    """

    def __init__(self, *, fence: ContinuationDeletionFence) -> None:
        # Alias-aware reads cannot prove that the new key itself was written.
        while isinstance(fence, LegacyAliasDeletionFence):
            fence = fence._fence
        self._fence = fence

    async def migrate(
        self, *, pairs: Sequence[FenceCarryForward], now: datetime
    ) -> FenceMigrationResult:
        if now.tzinfo is None:
            raise ValueError("now MUST be timezone-aware")
        if len(pairs) > MAX_FENCE_MIGRATION_BATCH:
            raise ValueError(f"batch MUST NOT exceed {MAX_FENCE_MIGRATION_BATCH} tombstones")
        carried: list[str] = []
        already_present: list[str] = []
        absent: list[str] = []
        pending: list[str] = []
        for pair in pairs:
            if not await self._read(pair.legacy_anchor_id):
                absent.append(pair.current_anchor_id)
                continue
            if await self._read(pair.current_anchor_id):
                already_present.append(pair.current_anchor_id)
                continue
            try:
                await self._fence.record(anchor_id=pair.current_anchor_id, at=now)
            except Exception as error:  # noqa: BLE001 - fail closed on any fence-write failure
                raise RetentionFenceUnavailableError(
                    "scheduled continuation deletion fence could not be carried forward"
                ) from error
            if await self._read(pair.current_anchor_id):
                carried.append(pair.current_anchor_id)
            else:
                pending.append(pair.current_anchor_id)
        return FenceMigrationResult(
            carried=tuple(carried),
            already_present=tuple(already_present),
            absent=tuple(absent),
            pending=tuple(pending),
        )

    async def _read(self, anchor_id: str) -> bool:
        try:
            return await self._fence.is_fenced(anchor_id=anchor_id)
        except Exception as error:  # noqa: BLE001 - fail closed on any fence-read failure
            raise RetentionFenceUnavailableError(
                "scheduled continuation deletion fence is unavailable"
            ) from error


def _fence_identifier(name: str, value: str) -> None:
    if not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


async def assert_not_fenced(fence: ContinuationDeletionFence, *, anchor_id: str) -> None:
    """Fail closed when the fence is unreadable and refuse a fenced anchor id."""
    try:
        fenced = await fence.is_fenced(anchor_id=anchor_id)
    except Exception as error:  # noqa: BLE001 - fail closed on any fence-read failure
        raise RetentionFenceUnavailableError(
            "scheduled continuation deletion fence is unavailable"
        ) from error
    if fenced:
        raise ContinuationDeletionFencedError(
            "scheduled continuation was deleted and MUST NOT be restored"
        )


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
        fence: ContinuationDeletionFence,
        grace: timedelta = timedelta(days=30),
    ) -> None:
        if grace < timedelta(0):
            raise ValueError("grace MUST NOT be negative")
        self._store = store
        self._holds = holds
        self._deleter = deleter
        self._audit = audit
        self._fence = fence
        self._grace = grace

    async def purge(self, *, anchor_id: str, now: datetime) -> RetentionResult:
        if now.tzinfo is None:
            raise ValueError("now MUST be timezone-aware")
        anchor = await self._store.get(anchor_id)
        if anchor is None:
            # The anchor is deleted last, so an absent anchor means every earlier
            # target already succeeded. Report the completed purge without revealing
            # whether the anchor ever existed.
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

        try:
            await self._fence.record(anchor_id=anchor.anchor_id, at=now)
            recorded = await self._fence.is_fenced(anchor_id=anchor.anchor_id)
        except Exception as error:  # noqa: BLE001 - fail closed on any fence failure
            raise RetentionFenceUnavailableError(
                "scheduled continuation deletion fence could not be recorded"
            ) from error
        if not recorded:
            # A silently dropped write would leave a late writer free to restore the body.
            raise RetentionFenceUnavailableError(
                "scheduled continuation deletion fence did not survive its readback"
            )

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
    "DELETION_FENCE_PREFIX",
    "MAX_FENCE_ALIASES",
    "MAX_FENCE_MIGRATION_BATCH",
    "MAX_RETENTION_BATCH",
    "RETENTION_ORDER",
    "RETENTION_WORKER_PRINCIPAL",
    "ContinuationDeletionFence",
    "ContinuationDeletionFencedError",
    "ContinuationFenceMigrator",
    "FenceCarryForward",
    "FenceMigrationResult",
    "InMemoryContinuationDeletionFence",
    "InMemoryLegalHoldRegistry",
    "InMemoryRetentionAuditSink",
    "LegacyAliasDeletionFence",
    "LegalHoldRegistry",
    "RetentionAuditEvent",
    "RetentionAuditSink",
    "RetentionDeleter",
    "RetentionFenceUnavailableError",
    "RetentionHoldUnavailableError",
    "RetentionNotExpiredError",
    "RetentionOutcome",
    "RetentionResult",
    "RetentionTarget",
    "ScheduledContinuationRetentionWorker",
    "StateStoreContinuationDeletionFence",
    "StateStoreRetentionAuditSink",
    "assert_not_fenced",
]
