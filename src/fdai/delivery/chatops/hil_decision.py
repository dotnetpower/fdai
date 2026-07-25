"""Event-bus transport for durable HIL decisions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Final

from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.hil_registry import HilApprovalRegistry, HilDecisionReceipt

DEFAULT_HIL_DECISION_TOPIC: Final[str] = "aw.hil.decisions"
_LOGGER = logging.getLogger(__name__)
HilDecisionPublisher = Callable[[HilDecisionReceipt], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class EventBusHilDecisionPublisher:
    bus: EventBus
    topic: str = DEFAULT_HIL_DECISION_TOPIC

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("HIL decision topic MUST be non-empty")

    async def __call__(self, receipt: HilDecisionReceipt) -> None:
        await self.bus.publish(
            self.topic,
            receipt.approval_id,
            {
                "approval_id": receipt.approval_id,
                "idempotency_key": receipt.idempotency_key,
                "decision": receipt.decision.value,
                "approver_oid": receipt.approver_oid,
                "justification": receipt.justification,
                "decided_at": receipt.decided_at.isoformat(),
                "receipt_ref": receipt.receipt_ref,
            },
        )

    async def close(self) -> None:
        close = getattr(self.bus, "close", None)
        if callable(close):
            await close()


async def attempt_hil_decision_delivery(
    *,
    registry: HilApprovalRegistry,
    publisher: HilDecisionPublisher,
    receipt: HilDecisionReceipt,
    timeout_seconds: float,
    max_delivery_attempts: int,
) -> tuple[HilDecisionReceipt, bool]:
    """Attempt one outbox delivery and durably checkpoint its outcome."""
    if receipt.delivered:
        return receipt, True
    if receipt.delivery_abandoned:
        return receipt, False
    try:
        async with asyncio.timeout(timeout_seconds):
            await publisher(receipt)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - persist a bounded transport failure
        updated = await registry.record_delivery_attempt(
            idempotency_key=receipt.idempotency_key,
            delivered=False,
            error_code=f"publish:{type(exc).__name__}",
            max_attempts=max_delivery_attempts,
        )
        return replace(updated, already_recorded=receipt.already_recorded), False
    updated = await registry.record_delivery_attempt(
        idempotency_key=receipt.idempotency_key,
        delivered=True,
        max_attempts=max_delivery_attempts,
    )
    return replace(updated, already_recorded=receipt.already_recorded), True


@dataclass(frozen=True, slots=True)
class HilDecisionRecoveryConfig:
    interval_seconds: float = 30.0
    publish_timeout_seconds: float = 10.0
    max_delivery_attempts: int = 8
    batch_size: int = 100

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0 or self.publish_timeout_seconds <= 0:
            raise ValueError("HIL decision recovery intervals MUST be positive")
        if self.max_delivery_attempts <= 0 or self.batch_size <= 0:
            raise ValueError("HIL decision recovery bounds MUST be positive")


@dataclass(slots=True)
class HilDecisionDeliveryRecovery:
    """Periodically redrive durable HIL decisions that have not reached the bus."""

    registry: HilApprovalRegistry
    publisher: HilDecisionPublisher
    config: HilDecisionRecoveryConfig = field(default_factory=HilDecisionRecoveryConfig)
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        await self.drain_once()
        self._task = asyncio.create_task(self._run(), name="hil-decision-delivery-recovery")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            await task
        self._task = None

    async def drain_once(self) -> int:
        delivered = 0
        receipts = await self.registry.list_undelivered(limit=self.config.batch_size)
        for receipt in receipts:
            try:
                _updated, succeeded = await attempt_hil_decision_delivery(
                    registry=self.registry,
                    publisher=self.publisher,
                    receipt=receipt,
                    timeout_seconds=self.config.publish_timeout_seconds,
                    max_delivery_attempts=self.config.max_delivery_attempts,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception(
                    "hil_decision_recovery_checkpoint_failed",
                    extra={"approval_id": receipt.approval_id},
                )
                continue
            delivered += int(succeeded)
        return delivered

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.config.interval_seconds,
                )
            except TimeoutError:
                await self.drain_once()


__all__ = [
    "DEFAULT_HIL_DECISION_TOPIC",
    "EventBusHilDecisionPublisher",
    "HilDecisionDeliveryRecovery",
    "HilDecisionRecoveryConfig",
    "attempt_hil_decision_delivery",
]
