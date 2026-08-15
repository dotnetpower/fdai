"""Bounded EventBus runtime for durable effect reconciliation delivery."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from fdai.core.ontology_platform.reconciliation import (
    EffectReconciliationCoordinator,
    ReconciliationLedger,
)
from fdai.core.ontology_platform.reconciliation_binding import (
    RECONCILIATION_OUTBOX_TOPIC,
    RECONCILIATION_REQUEST_TOPIC,
    EffectReconciliationBinder,
    ObservationContextVerifier,
    ReconciliationArtifactResolver,
)
from fdai.core.ontology_platform.reconciliation_contracts import ReconciliationOutcome
from fdai.core.ontology_platform.reconciliation_events import ReconciliationOutboxEvent
from fdai.shared.providers.event_bus import (
    EventBus,
    EventEnvelope,
    PublishReceipt,
    subscription,
)

_DEFAULT_EVENT_HANDLING_TIMEOUT_SECONDS = 5.0
_DEFAULT_PUBLISH_TIMEOUT_SECONDS = 2.0
_DEFAULT_OUTBOX_LEASE = timedelta(seconds=10)
_DEFAULT_RETRY_DELAY = timedelta(seconds=5)


class PublishTimeoutEventBus:
    """Apply a deadline to broker publication while preserving EventBus semantics.

    A timeout is raised to the binder as a publication failure. The binder then releases its
    durable claim to pending state; this adapter never retries publication inline.
    """

    def __init__(self, *, event_bus: EventBus, timeout_seconds: float = 2.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("reconciliation EventBus publish timeout MUST be positive")
        self._event_bus = event_bus
        self._timeout_seconds = timeout_seconds

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        """Publish once and raise ``TimeoutError`` when broker acknowledgement is late."""

        async with asyncio.timeout(self._timeout_seconds):
            return await self._event_bus.publish(topic, key, payload)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        """Delegate subscription without changing consumer-group ownership."""

        return self._event_bus.subscribe(topic, group_id)

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        """Delegate dead-letter publication to the underlying EventBus."""

        await self._event_bus.dead_letter(topic, key, payload, reason)


class EffectReconciliationWorker:
    """Consume reconciliation requests and drain proposal-only durable outbox events.

    Request processing is sequential to preserve broker ordering and bounded by one overall
    deadline. Outbox publication uses the binder's durable claim/release/ack protocol with a
    ten-second default lease. Errors and cancellation propagate so the runtime can restart or
    redeliver; this worker grants no execution authority and owns no workflow state.
    """

    def __init__(
        self,
        *,
        coordinator: EffectReconciliationCoordinator,
        ledger: ReconciliationLedger,
        event_bus: EventBus,
        artifact_resolver: ReconciliationArtifactResolver,
        observation_verifier: ObservationContextVerifier,
        claimant_id: str,
        group_id: str,
        clock: Callable[[], datetime],
        request_topic: str = RECONCILIATION_REQUEST_TOPIC,
        outbox_topic: str = RECONCILIATION_OUTBOX_TOPIC,
        event_handling_timeout_seconds: float = _DEFAULT_EVENT_HANDLING_TIMEOUT_SECONDS,
        publish_timeout_seconds: float = _DEFAULT_PUBLISH_TIMEOUT_SECONDS,
        outbox_lease: timedelta = _DEFAULT_OUTBOX_LEASE,
        retry_delay: timedelta = _DEFAULT_RETRY_DELAY,
    ) -> None:
        if not group_id:
            raise ValueError("reconciliation subscriber group id MUST be non-empty")
        if not request_topic:
            raise ValueError("reconciliation request topic MUST be non-empty")
        if event_handling_timeout_seconds <= 0:
            raise ValueError("reconciliation event handling timeout MUST be positive")
        bounded_event_bus = PublishTimeoutEventBus(
            event_bus=event_bus,
            timeout_seconds=publish_timeout_seconds,
        )
        self._event_bus = event_bus
        self._group_id = group_id
        self._request_topic = request_topic
        self._clock = clock
        self._event_handling_timeout_seconds = event_handling_timeout_seconds
        self._binder = EffectReconciliationBinder(
            coordinator=coordinator,
            ledger=ledger,
            event_bus=bounded_event_bus,
            artifact_resolver=artifact_resolver,
            observation_verifier=observation_verifier,
            claimant_id=claimant_id,
            outbox_topic=outbox_topic,
            lease_duration=outbox_lease,
            retry_delay=retry_delay,
        )

    async def handle_payload(self, payload: Mapping[str, Any]) -> ReconciliationOutcome:
        """Handle one untrusted request within the overall five-second default budget."""

        async with asyncio.timeout(self._event_handling_timeout_seconds):
            return await self._binder.handle_event(payload)

    async def run_subscriber(self) -> None:
        """Consume requests until the EventBus iterator ends or cancellation propagates."""

        async with subscription(self._event_bus, self._request_topic, self._group_id) as stream:
            async for envelope in stream:
                await self.handle_payload(envelope.payload)

    async def publish_pending_once(self) -> ReconciliationOutboxEvent | None:
        """Claim and publish at most one due outbox event without inline retry."""

        now = self._clock()
        _require_aware_clock(now)
        return await self._binder.publish_pending(now=now)

    async def drain_pending(self, *, limit: int = 100) -> tuple[ReconciliationOutboxEvent, ...]:
        """Drain a bounded batch using one deterministic clock reading."""

        now = self._clock()
        _require_aware_clock(now)
        return await self._binder.drain_pending(now=now, limit=limit)


def _require_aware_clock(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("reconciliation runtime clock MUST be timezone-aware")


__all__ = ["EffectReconciliationWorker", "PublishTimeoutEventBus"]
