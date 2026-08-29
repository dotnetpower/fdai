"""Deadline-driven independent observation worker for pending MSCP effects."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.mscp_profile.effect_verification import (
    EffectVerificationReason,
    EffectVerificationResult,
    EffectVerificationStatus,
    ObservedEffect,
    verify_effect,
)
from fdai.core.mscp_profile.pending_effect_store import (
    PendingEffectOwnershipError,
    PendingEffectRecord,
    PendingEffectStaleRevisionError,
    StateStorePendingEffectStore,
)


class PendingEffectObserver(Protocol):
    """Observe one expected effect without receiving executor success claims."""

    def __call__(
        self,
        record: PendingEffectRecord,
    ) -> Awaitable[ObservedEffect | None]: ...


@dataclass(frozen=True, slots=True)
class ObservationWorkerReport:
    """Bounded outcome counts for one worker pass."""

    considered: int
    verified: int
    mismatched: int
    held: int
    ownership_conflicts: int
    provider_failures: int
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("observation worker MUST NOT grant execution authority")


class PendingEffectObservationWorker:
    """Claim and complete pending effects outside the synchronous executor."""

    def __init__(
        self,
        *,
        store: StateStorePendingEffectStore,
        observer: PendingEffectObserver,
        owner_id: str,
        lease_seconds: int = 30,
        max_items: int = 100,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not owner_id.strip() or len(owner_id) > 256:
            raise ValueError("observation worker owner_id MUST be bounded non-empty text")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("observation worker lease_seconds MUST be between 1 and 300")
        if not 1 <= max_items <= 1_000:
            raise ValueError("observation worker max_items MUST be between 1 and 1000")
        self._store = store
        self._observer = observer
        self._owner_id = owner_id
        self._lease_seconds = lease_seconds
        self._max_items = max_items
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run_once(self) -> ObservationWorkerReport:
        """Observe one bounded ready batch with per-record failure isolation."""

        now = self._clock()
        records = await self._store.list_ready(now=now, limit=self._max_items)
        outcomes = await asyncio.gather(*(self._observe(record, now=now) for record in records))
        return ObservationWorkerReport(
            considered=len(records),
            verified=sum(outcome == "verified" for outcome in outcomes),
            mismatched=sum(outcome == "mismatch" for outcome in outcomes),
            held=sum(outcome in {"hold", "provider_failure"} for outcome in outcomes),
            ownership_conflicts=sum(outcome == "ownership_conflict" for outcome in outcomes),
            provider_failures=sum(outcome == "provider_failure" for outcome in outcomes),
        )

    async def _observe(self, record: PendingEffectRecord, *, now: datetime) -> str:
        try:
            claimed = await self._store.claim(
                record.expected.prediction_id,
                owner_id=self._owner_id,
                expected_revision=record.revision,
                now=now,
                lease_until=now + timedelta(seconds=self._lease_seconds),
            )
        except (PendingEffectOwnershipError, PendingEffectStaleRevisionError):
            return "ownership_conflict"

        provider_failed = False
        try:
            observed = await self._observer(claimed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - provider failures become explicit hold evidence
            provider_failed = True
            result = EffectVerificationResult(
                EffectVerificationStatus.HOLD,
                EffectVerificationReason.OBSERVATION_PROVIDER_FAILED,
            )
        else:
            result = (
                verify_effect(claimed.expected, observed)
                if observed is not None
                else EffectVerificationResult(
                    EffectVerificationStatus.HOLD,
                    EffectVerificationReason.OBSERVATION_UNAVAILABLE,
                )
            )

        completed_at = self._clock()
        try:
            await self._store.complete(
                claimed.expected.prediction_id,
                owner_id=self._owner_id,
                owner_generation=claimed.owner_generation,
                expected_revision=claimed.revision,
                completed_at=completed_at,
                result=result,
            )
        except (PendingEffectOwnershipError, PendingEffectStaleRevisionError):
            return "ownership_conflict"
        if provider_failed:
            return "provider_failure"
        return result.status.value


__all__ = [
    "ObservationWorkerReport",
    "PendingEffectObservationWorker",
    "PendingEffectObserver",
]
