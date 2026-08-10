"""Lease-based publication of proposal-only reconciliation recommendations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.reconciliation import (
    EffectReconciliationCoordinator,
    ReconciliationLedger,
    ReconciliationNextStep,
    ReconciliationPublication,
    ReconciliationRecommendation,
    StateStoreReconciliationLedger,
)
from fdai.core.ontology_platform.reconciliation_contracts import (
    RECONCILIATION_DECISION_TOPIC,
    RECONCILIATION_RECOVERY_TOPIC,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore

_MAX_PUBLICATION_ATTEMPTS = 5
_LOGGER = logging.getLogger("fdai.ontology.reconciliation_outbox")


@dataclass(frozen=True, slots=True)
class ReconciliationRuntimeBinding:
    """Production coordinator and publisher sharing one durable ledger."""

    ledger: StateStoreReconciliationLedger
    coordinator: EffectReconciliationCoordinator
    publisher: ReconciliationOutboxPublisher


class ReconciliationOutboxPublisher:
    """Publish durable recommendations to accountable agent command topics.

    The publisher is a mechanical relay. It never judges, invokes an agent,
    calls an executor, or grants authority. Broker acknowledgement closes only
    publication state; the owning agent still decides the next state transition.
    """

    def __init__(
        self,
        *,
        ledger: ReconciliationLedger,
        event_bus: EventBus,
        clock: Callable[[], datetime] | None = None,
        batch_limit: int = 100,
        lease_duration: timedelta = timedelta(seconds=60),
        retry_delay: timedelta = timedelta(seconds=30),
        idle_interval_seconds: float = 1.0,
        publish_timeout_seconds: float = 30.0,
    ) -> None:
        if not 1 <= batch_limit <= 100:
            raise ValueError("reconciliation outbox batch_limit MUST be between 1 and 100")
        if not timedelta(0) < lease_duration <= timedelta(minutes=5):
            raise ValueError("reconciliation outbox lease_duration MUST be positive and bounded")
        if not timedelta(0) < retry_delay <= timedelta(hours=1):
            raise ValueError("reconciliation outbox retry_delay MUST be positive and bounded")
        if not 0.01 <= idle_interval_seconds <= 300:
            raise ValueError("reconciliation outbox idle interval MUST be bounded")
        if not 0.1 <= publish_timeout_seconds < lease_duration.total_seconds():
            raise ValueError("reconciliation publish timeout MUST fit inside its lease")
        self._ledger = ledger
        self._event_bus = event_bus
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._batch_limit = batch_limit
        self._lease_duration = lease_duration
        self._retry_delay = retry_delay
        self._idle_interval_seconds = idle_interval_seconds
        self._publish_timeout_seconds = publish_timeout_seconds

    async def run_once(self) -> int:
        """Publish one bounded batch and return broker-acknowledged count."""

        now = self._now()
        publications = await self._ledger.claim_publications(
            now=now,
            limit=self._batch_limit,
            lease_until=now + self._lease_duration,
        )
        published = 0
        for publication in publications:
            if await self._publish_one(publication, now=now):
                published += 1
        return published

    async def _publish_one(
        self,
        publication: ReconciliationPublication,
        *,
        now: datetime,
    ) -> bool:
        recommendation = publication.recommendation
        lease_token = publication.lease_token
        if lease_token is None:
            raise ValueError("claimed reconciliation publication lacks a lease token")
        try:
            validated = ReconciliationRecommendation.model_validate(
                recommendation.model_dump(mode="json")
            )
            topic = _recommendation_topic(validated)
            async with asyncio.timeout(self._publish_timeout_seconds):
                receipt = await self._event_bus.publish(
                    topic,
                    validated.idempotency_key,
                    validated.model_dump(mode="json"),
                )
            await self._ledger.complete_publication(
                validated.reconciliation_id,
                validated.idempotency_key,
                published_at=now,
                topic=topic,
                partition=receipt.partition,
                offset=receipt.offset,
                lease_token=lease_token,
            )
            return True
        except (TypeError, ValueError) as exc:
            await self._dead_letter_or_release(publication, now=now, error=type(exc).__name__)
            return False
        except Exception as exc:  # noqa: BLE001 - broker boundary; durable row remains retryable
            error = type(exc).__name__
            if publication.attempts >= _MAX_PUBLICATION_ATTEMPTS:
                await self._dead_letter_or_release(publication, now=now, error=error)
            else:
                await self._ledger.release_publication(
                    recommendation.reconciliation_id,
                    recommendation.idempotency_key,
                    available_at=now + self._retry_delay,
                    error=error,
                    lease_token=lease_token,
                )
            return False

    async def _dead_letter_or_release(
        self,
        publication: ReconciliationPublication,
        *,
        now: datetime,
        error: str,
    ) -> None:
        recommendation = publication.recommendation
        lease_token = publication.lease_token
        if lease_token is None:
            raise ValueError("claimed reconciliation publication lacks a lease token")
        topic = _recommendation_topic(recommendation)
        try:
            await self._event_bus.dead_letter(
                topic,
                recommendation.idempotency_key,
                recommendation.model_dump(mode="json"),
                error,
            )
        except Exception as exc:  # noqa: BLE001 - preserve durable retry when DLQ is unavailable
            await self._ledger.release_publication(
                recommendation.reconciliation_id,
                recommendation.idempotency_key,
                available_at=now + self._retry_delay,
                error=type(exc).__name__,
                lease_token=lease_token,
            )
            return
        await self._ledger.dead_letter_publication(
            recommendation.reconciliation_id,
            recommendation.idempotency_key,
            failed_at=now,
            error=error,
            lease_token=lease_token,
        )

    async def run(self, stop: asyncio.Event) -> None:
        """Drain bounded batches until shutdown without polling while stopped."""

        while not stop.is_set():
            try:
                published = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - worker isolation; records remain durable
                _LOGGER.exception("reconciliation_outbox_iteration_failed")
                published = 0
            if published:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._idle_interval_seconds)
            except TimeoutError:
                continue

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError("reconciliation outbox clock MUST return an aware datetime")
        return value.astimezone(UTC)


def _recommendation_topic(recommendation: ReconciliationRecommendation) -> str:
    if recommendation.next_step is ReconciliationNextStep.REQUEST_VIDAR_RECOVERY:
        return RECONCILIATION_RECOVERY_TOPIC
    return RECONCILIATION_DECISION_TOPIC


def build_reconciliation_runtime(
    *,
    state_store: StateStore,
    event_bus: EventBus,
    clock: Callable[[], datetime] | None = None,
) -> ReconciliationRuntimeBinding:
    """Build production reconciliation and proposal publication composition."""

    ledger = StateStoreReconciliationLedger(store=state_store)
    return ReconciliationRuntimeBinding(
        ledger=ledger,
        coordinator=EffectReconciliationCoordinator(ledger=ledger),
        publisher=ReconciliationOutboxPublisher(
            ledger=ledger,
            event_bus=event_bus,
            clock=clock,
        ),
    )


__all__ = [
    "RECONCILIATION_DECISION_TOPIC",
    "RECONCILIATION_RECOVERY_TOPIC",
    "ReconciliationOutboxPublisher",
    "ReconciliationRuntimeBinding",
    "build_reconciliation_runtime",
]
