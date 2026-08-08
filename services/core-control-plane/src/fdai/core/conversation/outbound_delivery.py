"""Persist complete channel responses before bounded provider delivery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryError,
    ConversationChannelAdapter,
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    MAX_DELIVERY_ATTEMPTS,
    ConversationDeliveryStore,
    OutboundDeliveryAcknowledgement,
    OutboundDeliveryRecord,
    OutboundDeliveryState,
    new_delivery_record,
)


@dataclass(frozen=True, slots=True)
class DurableOutboundDeliveryConfig:
    worker_id: str
    lease_seconds: int = 30
    max_attempts: int = 4
    freshness_seconds: int = 900
    retention_seconds: int = 2_592_000
    base_retry_seconds: int = 5
    max_retry_seconds: int = 300
    claim_limit: int = 50

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("delivery worker_id MUST be non-empty")
        if not 1 <= self.max_attempts <= MAX_DELIVERY_ATTEMPTS:
            raise ValueError("delivery max_attempts is outside the bounded range")
        if not 1 <= self.lease_seconds <= 300:
            raise ValueError("delivery lease_seconds is outside the bounded range")
        if not 1 <= self.base_retry_seconds <= self.max_retry_seconds <= 3600:
            raise ValueError("delivery retry bounds are invalid")
        if not 1 <= self.claim_limit <= 200:
            raise ValueError("delivery claim_limit is invalid")
        if self.freshness_seconds < self.lease_seconds:
            raise ValueError("delivery freshness MUST cover one lease")
        if self.retention_seconds < self.freshness_seconds:
            raise ValueError("delivery retention MUST cover freshness")


class AdapterHealthGate(Protocol):
    """Minimal health seam used by delivery without importing a concrete breaker."""

    async def can_send(self, *, adapter_id: str) -> bool: ...

    async def record_success(
        self,
        *,
        adapter_id: str,
        channel_kind: ConversationChannelKind,
        at: datetime,
    ) -> None: ...

    async def record_failure(
        self,
        *,
        adapter_id: str,
        channel_kind: ConversationChannelKind,
        at: datetime,
        error_code: str,
    ) -> None: ...


class DurableOutboundDeliveryCoordinator:
    """Own persistence, CAS claim, send, acknowledgement, and bounded retry."""

    def __init__(
        self,
        *,
        store: ConversationDeliveryStore,
        channels: Mapping[ConversationChannelKind, ConversationChannelAdapter],
        config: DurableOutboundDeliveryConfig,
        health: AdapterHealthGate | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        for kind, channel in channels.items():
            if channel.channel_kind is not kind:
                raise ValueError("delivery channel mapping kind mismatch")
        self._store = store
        self._channels = dict(channels)
        self._config = config
        self._health = health
        self._clock = clock or (lambda: datetime.now(UTC))

    async def submit(
        self,
        *,
        origin_ref: str,
        principal_id: str,
        scope_ref: str,
        conversation_id: str,
        binding_id: str | None,
        response: OutboundResponse,
        send_immediately: bool = True,
    ) -> OutboundDeliveryRecord:
        created_at = self._clock()
        record = await self._store.put(
            new_delivery_record(
                origin_ref=origin_ref,
                principal_id=principal_id,
                scope_ref=scope_ref,
                conversation_id=conversation_id,
                binding_id=binding_id,
                response=response,
                created_at=created_at,
                freshness=timedelta(seconds=self._config.freshness_seconds),
                retention=timedelta(seconds=self._config.retention_seconds),
            )
        )
        if not send_immediately or record.state.immutable:
            return record
        return await self.deliver(record.delivery_id)

    async def deliver(self, delivery_id: str) -> OutboundDeliveryRecord:
        current = await self._store.get(delivery_id)
        if current is None:
            raise KeyError(delivery_id)
        if current.state.immutable:
            return current
        now = self._clock()
        adapter_id = current.response.channel_kind.value
        if self._health is not None and not await self._health.can_send(adapter_id=adapter_id):
            return current
        claimed = await self._store.claim(
            delivery_id=delivery_id,
            now=now,
            worker_id=self._config.worker_id,
            lease_seconds=self._config.lease_seconds,
        )
        if claimed is None:
            return current
        return await self._send_claimed(claimed)

    async def drain_due(self) -> tuple[OutboundDeliveryRecord, ...]:
        now = self._clock()
        claimed = await self._store.claim_due(
            now=now,
            worker_id=self._config.worker_id,
            lease_seconds=self._config.lease_seconds,
            limit=self._config.claim_limit,
        )
        results: list[OutboundDeliveryRecord] = []
        for record in claimed:
            adapter_id = record.response.channel_kind.value
            if self._health is not None and not await self._health.can_send(adapter_id=adapter_id):
                results.append(
                    await self._finish_failure(
                        record,
                        at=self._clock(),
                        error_code="adapter_unavailable",
                    )
                )
                continue
            results.append(await self._send_claimed(record))
        return tuple(results)

    async def reconcile_startup(self) -> int:
        return await self._store.reconcile_sending(now=self._clock())

    async def _send_claimed(self, record: OutboundDeliveryRecord) -> OutboundDeliveryRecord:
        channel = self._channels.get(record.response.channel_kind)
        if channel is None:
            return await self._finish_failure(
                record,
                at=self._clock(),
                error_code="adapter_missing",
            )
        adapter_id = record.response.channel_kind.value
        try:
            receipt = await channel.send(record.response)
        except ChannelDeliveryError as exc:
            if self._health is not None:
                await self._health.record_failure(
                    adapter_id=adapter_id,
                    channel_kind=record.response.channel_kind,
                    at=self._clock(),
                    error_code=exc.code,
                )
            if exc.acknowledgement_ambiguous:
                return await self._finish_ambiguous(record, error_code=exc.code)
            return await self._finish_failure(record, at=self._clock(), error_code=exc.code)
        except BaseException:
            if self._health is not None:
                await self._health.record_failure(
                    adapter_id=adapter_id,
                    channel_kind=record.response.channel_kind,
                    at=self._clock(),
                    error_code="send_interrupted",
                )
            return await self._finish_ambiguous(record, error_code="send_interrupted")
        if receipt is None or receipt.message_id is None:
            if self._health is not None:
                await self._health.record_failure(
                    adapter_id=adapter_id,
                    channel_kind=record.response.channel_kind,
                    at=self._clock(),
                    error_code="ack_missing",
                )
            return await self._finish_ambiguous(record, error_code="ack_missing")
        acknowledged_at = self._clock()
        if self._health is not None:
            await self._health.record_success(
                adapter_id=adapter_id,
                channel_kind=record.response.channel_kind,
                at=acknowledged_at,
            )
        return await self._store.finish(
            delivery_id=record.delivery_id,
            worker_id=self._config.worker_id,
            expected_attempt_count=record.attempt_count,
            state=OutboundDeliveryState.DELIVERED,
            at=acknowledged_at,
            acknowledgement=OutboundDeliveryAcknowledgement(
                delivery_id=record.delivery_id,
                attempt_id=f"{record.delivery_id}:attempt:{record.attempt_count}",
                provider_message_id=receipt.message_id,
                acknowledged_at=acknowledged_at,
                degraded_to_text=receipt.degraded_to_text,
            ),
        )

    async def _finish_ambiguous(
        self,
        record: OutboundDeliveryRecord,
        *,
        error_code: str,
    ) -> OutboundDeliveryRecord:
        return await self._store.finish(
            delivery_id=record.delivery_id,
            worker_id=self._config.worker_id,
            expected_attempt_count=record.attempt_count,
            state=OutboundDeliveryState.AMBIGUOUS,
            at=self._clock(),
            error_code=error_code,
        )

    async def _finish_failure(
        self,
        record: OutboundDeliveryRecord,
        *,
        at: datetime,
        error_code: str,
    ) -> OutboundDeliveryRecord:
        delay = min(
            self._config.max_retry_seconds,
            self._config.base_retry_seconds * (2 ** max(record.attempt_count - 1, 0)),
        )
        next_due_at = at + timedelta(seconds=delay)
        exhausted = (
            record.attempt_count >= self._config.max_attempts or next_due_at >= record.expires_at
        )
        return await self._store.finish(
            delivery_id=record.delivery_id,
            worker_id=self._config.worker_id,
            expected_attempt_count=record.attempt_count,
            state=(OutboundDeliveryState.ABANDONED if exhausted else OutboundDeliveryState.FAILED),
            at=at,
            next_due_at=None if exhausted else next_due_at,
            error_code=error_code,
        )


__all__ = [
    "AdapterHealthGate",
    "DurableOutboundDeliveryConfig",
    "DurableOutboundDeliveryCoordinator",
]
