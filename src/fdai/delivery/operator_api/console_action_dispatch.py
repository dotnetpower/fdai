"""Durable at-least-once delivery for FDAI Console action proposals."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fdai.shared.providers.event_bus import EventBus

from .console_action_dispatch_models import (
    ConsoleActionDispatch,
    ConsoleActionDispatchConflictError,
    ConsoleActionDispatchState,
)
from .console_action_dispatch_store import (
    ConsoleActionDispatchStore,
    console_action_dispatch_id,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConsoleActionDispatcherConfig:
    worker_id: str = "console-action-dispatch"
    lease_seconds: int = 30
    publish_timeout_seconds: int = 10
    retry_delay_seconds: int = 30
    batch_size: int = 100

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("console action dispatcher worker_id MUST be non-empty")
        if (
            min(
                self.lease_seconds,
                self.publish_timeout_seconds,
                self.retry_delay_seconds,
                self.batch_size,
            )
            < 1
        ):
            raise ValueError("console action dispatcher bounds MUST be positive")


@dataclass(frozen=True, slots=True)
class ConsoleActionDispatcher:
    store: ConsoleActionDispatchStore
    event_bus: EventBus
    config: ConsoleActionDispatcherConfig = field(default_factory=ConsoleActionDispatcherConfig)
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    async def submit(
        self,
        *,
        idempotency_key: str,
        intent_digest: str,
        topic: str,
        partition_key: str,
        payload: Mapping[str, object],
        correlation_id: str,
        actor_oid: str,
    ) -> ConsoleActionDispatch:
        record, _created = await self.store.enqueue(
            idempotency_key=idempotency_key,
            intent_digest=intent_digest,
            topic=topic,
            partition_key=partition_key,
            payload=payload,
            correlation_id=correlation_id,
            actor_oid=actor_oid,
            now=self.clock(),
        )
        if record.state is ConsoleActionDispatchState.PUBLISHED:
            return record
        await self.deliver(record.dispatch_id)
        refreshed = await self.store.get(record.dispatch_id)
        if refreshed is None:  # pragma: no cover - store invariant
            raise RuntimeError("console action dispatch vanished after delivery")
        return refreshed

    async def prepare_blocked(
        self,
        *,
        idempotency_key: str,
        intent_digest: str,
        topic: str,
        partition_key: str,
        payload: Mapping[str, object],
        correlation_id: str,
        actor_oid: str,
    ) -> ConsoleActionDispatch:
        record, _created = await self.store.enqueue(
            idempotency_key=idempotency_key,
            intent_digest=intent_digest,
            topic=topic,
            partition_key=partition_key,
            payload=payload,
            correlation_id=correlation_id,
            actor_oid=actor_oid,
            now=self.clock(),
            initial_state=ConsoleActionDispatchState.BLOCKED,
        )
        return record

    async def activate_and_deliver(self, dispatch_id: str) -> ConsoleActionDispatch:
        activated = await self.store.activate(dispatch_id, now=self.clock())
        if activated is None:
            raise RuntimeError("console action blocked dispatch does not exist")
        if activated.state is not ConsoleActionDispatchState.PUBLISHED:
            await self.deliver(dispatch_id)
        refreshed = await self.store.get(dispatch_id)
        if refreshed is None:  # pragma: no cover - store invariant
            raise RuntimeError("console action dispatch vanished after activation")
        return refreshed

    async def activate_and_deliver_key(self, idempotency_key: str) -> ConsoleActionDispatch:
        return await self.activate_and_deliver(console_action_dispatch_id(idempotency_key))

    async def deliver(self, dispatch_id: str) -> bool:
        claimed = await self.store.claim(
            dispatch_id,
            now=self.clock(),
            lease_owner=self.config.worker_id,
            lease_seconds=self.config.lease_seconds,
        )
        if claimed is None:
            current = await self.store.get(dispatch_id)
            return current is not None and current.state is ConsoleActionDispatchState.PUBLISHED
        try:
            async with asyncio.timeout(self.config.publish_timeout_seconds):
                await self.event_bus.publish(
                    claimed.topic,
                    claimed.partition_key,
                    dict(claimed.payload),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - durable retry owns transport failures
            await self.store.deferred(
                claimed,
                lease_owner=self.config.worker_id,
                now=self.clock(),
                retry_at=self.clock() + timedelta(seconds=self.config.retry_delay_seconds),
                error=f"publish:{type(exc).__name__}",
            )
            return False
        try:
            await self.store.published(
                claimed,
                lease_owner=self.config.worker_id,
                now=self.clock(),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "console_action_dispatch_receipt_failed",
                extra={"dispatch_id": claimed.dispatch_id},
            )
            return False
        return True

    async def drain_due(self) -> int:
        records = await self.store.due(now=self.clock(), limit=self.config.batch_size)
        delivered = 0
        for record in records:
            try:
                delivered += int(await self.deliver(record.dispatch_id))
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception(
                    "console_action_dispatch_recovery_failed",
                    extra={"dispatch_id": record.dispatch_id},
                )
        return delivered


@dataclass(slots=True)
class ConsoleActionDispatchRecovery:
    dispatcher: ConsoleActionDispatcher
    interval_seconds: float = 30
    reconcile: Callable[[], Awaitable[object]] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("console action recovery interval MUST be positive")

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        await self._recover_once()
        self._task = asyncio.create_task(self._run(), name="console-action-dispatch-recovery")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                try:
                    await self._recover_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.exception("console_action_dispatch_recovery_cycle_failed")

    async def _recover_once(self) -> None:
        if self.reconcile is not None:
            await self.reconcile()
        await self.dispatcher.drain_due()


def console_action_intent_digest(
    *,
    topic: str,
    partition_key: str,
    payload: Mapping[str, object],
) -> str:
    canonical_payload = dict(payload)
    canonical_payload.pop("correlation_id", None)
    encoded = json.dumps(
        {"topic": topic, "partition_key": partition_key, "payload": canonical_payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ConsoleActionDispatch",
    "ConsoleActionDispatchConflictError",
    "ConsoleActionDispatchRecovery",
    "ConsoleActionDispatchState",
    "ConsoleActionDispatchStore",
    "ConsoleActionDispatcher",
    "ConsoleActionDispatcherConfig",
    "console_action_intent_digest",
]
