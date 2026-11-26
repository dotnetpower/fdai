"""Supervise process-loss reconciliation, due delivery, and adapter breakers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelAdapterBreaker,
    ChannelBreakerMode,
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    ChannelKind,
)


class DueChannelDeliveryStore(Protocol):
    """Lease due delivery and compare-and-set persisted breaker state."""

    async def reconcile_sending(self, *, now: datetime) -> int: ...

    async def claim_due(
        self,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
        limit: int,
        channel_kind: ChannelKind | None = None,
    ) -> tuple[ChannelDeliveryRecord, ...]: ...

    async def get_breaker(self, adapter_id: str) -> ChannelAdapterBreaker | None: ...

    async def put_breaker(
        self,
        record: ChannelAdapterBreaker,
        *,
        expected_revision: int | None,
    ) -> ChannelAdapterBreaker: ...


class ClaimedChannelDeliveryHandler(Protocol):
    """Close one already leased delivery through its configured publisher."""

    async def deliver_claimed(self, record: ChannelDeliveryRecord) -> ChannelDeliveryRecord: ...


@dataclass(frozen=True, slots=True)
class ChannelDeliveryWorkerConfig:
    """Configure bounded delivery batches, leases, wake interval, and breaker threshold."""

    worker_id: str = "operator-channel-edge"
    channels: tuple[ChannelKind, ...] = (ChannelKind.SLACK, ChannelKind.TEAMS)
    lease_seconds: int = 30
    batch_size: int = 32
    idle_seconds: float = 5.0
    failure_threshold: int = 3
    failure_window: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if not self.worker_id or len(self.worker_id) > 256:
            raise ValueError("channel worker_id MUST be bounded and non-empty")
        if not self.channels or len(set(self.channels)) != len(self.channels):
            raise ValueError("channel worker channels MUST be unique and non-empty")
        if any(channel not in {ChannelKind.SLACK, ChannelKind.TEAMS} for channel in self.channels):
            raise ValueError("channel worker contains an unsupported channel")
        if not 1 <= self.lease_seconds <= 300 or not 1 <= self.batch_size <= 200:
            raise ValueError("channel worker lease or batch bound is invalid")
        if self.idle_seconds <= 0:
            raise ValueError("channel worker idle_seconds MUST be positive")
        if not 1 <= self.failure_threshold <= 20 or self.failure_window <= timedelta(0):
            raise ValueError("channel worker breaker threshold is invalid")


class ChannelDeliveryWorker:
    """Run bounded due batches while persisted breaker state admits provider I/O."""

    def __init__(
        self,
        *,
        store: DueChannelDeliveryStore,
        handler: ClaimedChannelDeliveryHandler,
        config: ChannelDeliveryWorkerConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._handler = handler
        self._config = config or ChannelDeliveryWorkerConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ready = False
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def ready(self) -> bool:
        """Return whether startup reconciliation and breaker creation completed."""
        return self._ready and self._task is not None and not self._task.done()

    async def initialize(self) -> int:
        """Reconcile expired sends and ensure every configured breaker exists."""
        now = _aware(self._clock())
        reconciled = await self._store.reconcile_sending(now=now)
        for channel in self._config.channels:
            adapter_id = _adapter_id(channel)
            if await self._store.get_breaker(adapter_id) is not None:
                continue
            initial = ChannelAdapterBreaker(
                adapter_id=adapter_id,
                channel_kind=channel,
                mode=ChannelBreakerMode.CLOSED,
                revision=0,
                updated_at=now,
                updated_by=self._config.worker_id,
                reason="initialized",
            )
            try:
                await self._store.put_breaker(initial, expected_revision=None)
            except ValueError:
                if await self._store.get_breaker(adapter_id) is None:
                    raise
        self._ready = True
        return reconciled

    async def start(self) -> None:
        """Initialize synchronously, then supervise bounded due batches."""
        if self._task is not None:
            return
        await self.initialize()
        self._task = asyncio.create_task(self._run(), name="operator-channel-delivery")

    def wake(self) -> None:
        """Request an immediate due scan after new durable work arrives."""
        self._wake.set()

    async def close(self) -> None:
        """Cancel and join the delivery worker without orphaning a task."""
        task, self._task = self._task, None
        self._ready = False
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def run_once(self) -> int:
        """Deliver one bounded admitted batch per configured channel."""
        if not self._ready:
            raise RuntimeError("channel delivery worker is not initialized")
        processed = 0
        for channel in self._config.channels:
            breaker = await self._store.get_breaker(_adapter_id(channel))
            if breaker is None or breaker.mode is not ChannelBreakerMode.CLOSED:
                continue
            now = _aware(self._clock())
            records = await self._store.claim_due(
                now=now,
                worker_id=self._config.worker_id,
                lease_seconds=self._config.lease_seconds,
                limit=self._config.batch_size,
                channel_kind=channel,
            )
            for record in records:
                closed = await self._handler.deliver_claimed(record)
                processed += 1
                await self._observe(breaker, closed, at=_aware(self._clock()))
                refreshed = await self._store.get_breaker(breaker.adapter_id)
                if refreshed is None or refreshed.mode is not ChannelBreakerMode.CLOSED:
                    break
                breaker = refreshed
        return processed

    async def _run(self) -> None:
        while True:
            processed = await self.run_once()
            if processed:
                await asyncio.sleep(0)
                continue
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._config.idle_seconds)
            except TimeoutError:
                pass

    async def _observe(
        self,
        breaker: ChannelAdapterBreaker,
        record: ChannelDeliveryRecord,
        *,
        at: datetime,
    ) -> None:
        cutoff = at - self._config.failure_window
        failures = tuple(value for value in breaker.failure_timestamps if value >= cutoff)
        if record.state is ChannelDeliveryState.DELIVERED:
            failures = ()
            reason = "delivery succeeded"
            mode = ChannelBreakerMode.CLOSED
        elif record.state in {
            ChannelDeliveryState.FAILED,
            ChannelDeliveryState.AMBIGUOUS,
            ChannelDeliveryState.ABANDONED,
        }:
            failures = (*failures, at)
            mode = (
                ChannelBreakerMode.OPEN
                if len(failures) >= self._config.failure_threshold
                else ChannelBreakerMode.CLOSED
            )
            reason = (
                "failure threshold reached"
                if mode is ChannelBreakerMode.OPEN
                else "failure observed"
            )
        else:
            return
        if failures == breaker.failure_timestamps and mode is breaker.mode:
            return
        updated = replace(
            breaker,
            mode=mode,
            failure_timestamps=failures,
            revision=breaker.revision + 1,
            updated_at=at,
            updated_by=self._config.worker_id,
            reason=reason,
        )
        try:
            await self._store.put_breaker(updated, expected_revision=breaker.revision)
        except ValueError:
            return


def _adapter_id(channel: ChannelKind) -> str:
    return f"operator-channel-edge:{channel.value}"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("channel worker clock MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["ChannelDeliveryWorker", "ChannelDeliveryWorkerConfig"]
