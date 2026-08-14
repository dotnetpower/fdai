"""Lease-fenced EventBus publication for durable reconciliation requests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

from fdai.core.ontology_platform.reconciliation_binding import RECONCILIATION_REQUEST_TOPIC
from fdai.core.ontology_platform.reconciliation_events import EffectReconciliationRequestEvent
from fdai.core.ontology_platform.reconciliation_request_outbox import (
    ReconciliationRequestOutbox,
)
from fdai.shared.providers.event_bus import EventBus


class ReconciliationRequestPublishRetryableError(RuntimeError):
    """The broker attempt failed after the durable claim was released."""


class ReconciliationRequestReceiptMismatchError(RuntimeError):
    """The broker acknowledged a topic other than the requested topic."""


class EffectReconciliationRequestPublisher:
    """Publish exact or oldest-pending requests through a durable leased outbox."""

    def __init__(
        self,
        *,
        outbox: ReconciliationRequestOutbox,
        event_bus: EventBus,
        claimant_id: str,
        clock: Callable[[], datetime],
        topic: str = RECONCILIATION_REQUEST_TOPIC,
        publish_timeout_seconds: float = 2.0,
        lease_duration: timedelta = timedelta(seconds=10),
        retry_delay: timedelta = timedelta(seconds=5),
    ) -> None:
        if not claimant_id:
            raise ValueError("reconciliation request publisher claimant id MUST be non-empty")
        if not topic:
            raise ValueError("reconciliation request topic MUST be non-empty")
        if publish_timeout_seconds <= 0:
            raise ValueError("reconciliation request publish timeout MUST be positive")
        if lease_duration <= timedelta(0) or retry_delay < timedelta(0):
            raise ValueError("reconciliation request outbox timing MUST be non-negative")
        if publish_timeout_seconds >= lease_duration.total_seconds():
            raise ValueError("reconciliation request publish timeout MUST be shorter than lease")
        if retry_delay > lease_duration:
            raise ValueError("reconciliation request retry delay MUST fit within lease")
        self._outbox = outbox
        self._event_bus = event_bus
        self._claimant_id = claimant_id
        self._clock = clock
        self._topic = topic
        self._publish_timeout_seconds = publish_timeout_seconds
        self._lease_duration = lease_duration
        self._retry_delay = retry_delay

    async def publish(
        self,
        request_id: str | None = None,
    ) -> EffectReconciliationRequestEvent | None:
        """Publish one exact request or the oldest due request without inline retry."""

        claimed_at = self._clock()
        _require_aware(claimed_at)
        if request_id is not None:
            event = await self._outbox.claim(
                request_id,
                claimant_id=self._claimant_id,
                now=claimed_at,
                lease_until=claimed_at + self._lease_duration,
            )
        else:
            event = await self._outbox.claim_next(
                claimant_id=self._claimant_id,
                now=claimed_at,
                lease_until=claimed_at + self._lease_duration,
            )
        if event is None:
            return None
        try:
            async with asyncio.timeout(self._publish_timeout_seconds):
                receipt = await self._event_bus.publish(
                    self._topic,
                    event.reconciliation_id,
                    event.model_dump(mode="json"),
                )
            if receipt.topic != self._topic:
                raise ReconciliationRequestReceiptMismatchError(
                    "reconciliation request broker receipt topic does not match"
                )
        except Exception as exc:
            error = (
                "broker_receipt_topic_mismatch"
                if isinstance(exc, ReconciliationRequestReceiptMismatchError)
                else "broker_publish_timeout"
                if isinstance(exc, TimeoutError)
                else "broker_publish_failed"
            )
            await self._outbox.release(
                event.observation_attempt_id,
                claimant_id=self._claimant_id,
                available_at=claimed_at + self._retry_delay,
                error=error,
            )
            if isinstance(exc, ReconciliationRequestReceiptMismatchError):
                raise
            raise ReconciliationRequestPublishRetryableError(error) from exc
        await self._outbox.complete(
            event.observation_attempt_id,
            claimant_id=self._claimant_id,
            published_at=claimed_at,
        )
        return event

    async def drain_pending(
        self,
        *,
        limit: int = 100,
    ) -> tuple[EffectReconciliationRequestEvent, ...]:
        """Publish a bounded oldest-first batch."""

        if not 1 <= limit <= 1000:
            raise ValueError("reconciliation request drain limit MUST be in [1, 1000]")
        published: list[EffectReconciliationRequestEvent] = []
        for _ in range(limit):
            event = await self.publish()
            if event is None:
                break
            published.append(event)
        return tuple(published)


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("reconciliation request publisher clock MUST be timezone-aware")


__all__ = [
    "EffectReconciliationRequestPublisher",
    "ReconciliationRequestPublishRetryableError",
    "ReconciliationRequestReceiptMismatchError",
]
