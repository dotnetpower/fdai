"""Bounded EventBus publication for durable Rule generation activation results."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationActivationResultEvent,
)
from fdai.shared.providers.event_bus import EventBus

from .ledger import RuleGenerationOutboxLedger

RULE_GENERATION_ACTIVATION_COMMAND_TOPIC = "rule.semantic-generation.activation-commands"
RULE_GENERATION_ACTIVATION_RESULT_TOPIC = "rule.semantic-generation.activation-results"


class RuleGenerationPublishRetryableError(RuntimeError):
    """The broker attempt failed after the durable claim was released."""


class RuleGenerationReceiptMismatchError(RuntimeError):
    """The broker acknowledged a topic other than the requested topic."""


class RuleGenerationOutboxPublisher:
    """Publish leased activation results and acknowledge only an exact broker receipt.

    Publication is at least once. Broker failures are released for durable retry, while task
    cancellation leaves the claim leased so another runtime can reclaim it after expiry.
    """

    def __init__(
        self,
        *,
        ledger: RuleGenerationOutboxLedger,
        event_bus: EventBus,
        claimant_id: str,
        clock: Callable[[], datetime],
        topic: str = RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
        publish_timeout_seconds: float = 2.0,
        lease_duration: timedelta = timedelta(seconds=10),
        retry_delay: timedelta = timedelta(seconds=5),
    ) -> None:
        if not claimant_id:
            raise ValueError("Rule generation publisher claimant id MUST be non-empty")
        if not topic:
            raise ValueError("Rule generation activation result topic MUST be non-empty")
        if publish_timeout_seconds <= 0:
            raise ValueError("Rule generation publish timeout MUST be positive")
        if lease_duration <= timedelta(0) or retry_delay < timedelta(0):
            raise ValueError("Rule generation outbox timing MUST be non-negative")
        if publish_timeout_seconds >= lease_duration.total_seconds():
            raise ValueError("Rule generation publish timeout MUST be shorter than its lease")
        if retry_delay > lease_duration:
            raise ValueError("Rule generation retry delay MUST fit within its lease")
        self._ledger = ledger
        self._event_bus = event_bus
        self._claimant_id = claimant_id
        self._clock = clock
        self._topic = topic
        self._publish_timeout_seconds = publish_timeout_seconds
        self._lease_duration = lease_duration
        self._retry_delay = retry_delay

    async def publish_pending_once(self) -> RuleGenerationActivationResultEvent | None:
        """Claim and publish at most one due result without retrying inline."""

        claimed_at = self._clock()
        _require_aware_clock(claimed_at)
        result = await self._ledger.claim_outbox(
            claimant_id=self._claimant_id,
            now=claimed_at,
            lease_until=claimed_at + self._lease_duration,
        )
        if result is None:
            return None
        request_id = _generation_request_id(result)
        try:
            async with asyncio.timeout(self._publish_timeout_seconds):
                receipt = await self._event_bus.publish(
                    self._topic,
                    request_id,
                    result.model_dump(mode="json"),
                )
            if receipt.topic != self._topic:
                raise RuleGenerationReceiptMismatchError(
                    "Rule generation broker receipt topic does not match"
                )
        except Exception as exc:
            if isinstance(exc, RuleGenerationReceiptMismatchError):
                error = "broker_receipt_topic_mismatch"
            elif isinstance(exc, TimeoutError):
                error = "broker_publish_timeout"
            else:
                error = "broker_publish_failed"
            await self._ledger.release_outbox(
                request_id,
                result.idempotency_key,
                claimant_id=self._claimant_id,
                available_at=claimed_at + self._retry_delay,
                error=error,
            )
            if isinstance(exc, RuleGenerationReceiptMismatchError):
                raise
            raise RuleGenerationPublishRetryableError(error) from exc
        await self._ledger.complete_outbox(
            request_id,
            result.idempotency_key,
            claimant_id=self._claimant_id,
            published_at=claimed_at,
        )
        return result

    async def drain_pending(
        self,
        *,
        limit: int = 100,
    ) -> tuple[RuleGenerationActivationResultEvent, ...]:
        """Publish a bounded batch so one backlog cannot monopolize the runtime."""

        if limit < 1 or limit > 1000:
            raise ValueError("Rule generation outbox drain limit MUST be between 1 and 1000")
        published: list[RuleGenerationActivationResultEvent] = []
        for _ in range(limit):
            result = await self.publish_pending_once()
            if result is None:
                break
            published.append(result)
        return tuple(published)


def _generation_request_id(result: RuleGenerationActivationResultEvent) -> str:
    return result.command.validation_result.build_result.request.generation_request_id


def _require_aware_clock(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Rule generation publisher clock MUST be timezone-aware")


__all__ = [
    "RULE_GENERATION_ACTIVATION_COMMAND_TOPIC",
    "RULE_GENERATION_ACTIVATION_RESULT_TOPIC",
    "RuleGenerationOutboxPublisher",
    "RuleGenerationPublishRetryableError",
    "RuleGenerationReceiptMismatchError",
]
