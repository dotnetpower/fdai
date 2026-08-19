"""Define dependency and result contracts for Operator channel delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelAdapterBreaker,
    ChannelDeliveryAcknowledgement,
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    PrincipalChannelBinding,
)
from fdai_operator_service.families.conversation.channel_edge.models import (
    ChannelDeliveryReceipt,
    RenderedChannelMessage,
)
from fdai_operator_service.families.conversation.contracts import PrincipalScope


@dataclass(frozen=True, slots=True)
class ChannelPrincipalContext:
    """Bind a canonical principal to server-owned semantic scope and locale."""

    scope: PrincipalScope
    scope_ref: str
    locale: str = "en"

    def __post_init__(self) -> None:
        if not self.scope_ref or len(self.scope_ref) > 512:
            raise ValueError("channel principal scope_ref MUST be bounded and non-empty")
        if not self.locale or len(self.locale) > 32:
            raise ValueError("channel principal locale MUST be bounded and non-empty")


class ChannelPrincipalResolver(Protocol):
    """Resolve only pre-authorized canonical principals to semantic scope."""

    async def resolve(self, principal_id: str) -> ChannelPrincipalContext: ...


class ChannelMessageLedger(Protocol):
    """Own inbound provider-message processing claims."""

    async def claim(self, idempotency_key: str) -> bool: ...

    async def complete(self, idempotency_key: str) -> None: ...

    async def release(self, idempotency_key: str) -> None: ...


class ChannelBindingStore(Protocol):
    """Persist and replay verified principal endpoint ownership."""

    async def create(self, binding: PrincipalChannelBinding) -> PrincipalChannelBinding: ...

    async def get(self, binding_id: str) -> PrincipalChannelBinding | None: ...


class ChannelDeliveryStore(Protocol):
    """Persist, lease, and close outbound provider delivery state."""

    async def put(self, record: ChannelDeliveryRecord) -> ChannelDeliveryRecord: ...

    async def get(self, delivery_id: str) -> ChannelDeliveryRecord | None: ...

    async def get_breaker(self, adapter_id: str) -> ChannelAdapterBreaker | None: ...

    async def claim(
        self,
        *,
        delivery_id: str,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> ChannelDeliveryRecord | None: ...

    async def finish(
        self,
        *,
        delivery_id: str,
        worker_id: str,
        expected_attempt_count: int,
        state: ChannelDeliveryState,
        at: datetime,
        next_due_at: datetime | None = None,
        error_code: str | None = None,
        acknowledgement: ChannelDeliveryAcknowledgement | None = None,
    ) -> ChannelDeliveryRecord: ...


class ChannelPublisher(Protocol):
    """Publish one pre-rendered provider message without semantic authority."""

    async def send(self, message: RenderedChannelMessage) -> ChannelDeliveryReceipt: ...


@dataclass(frozen=True, slots=True)
class ChannelDeliveryPipelineConfig:
    """Configure bounded leases, freshness, retention, and retry intervals."""

    worker_id: str = "operator-channel-edge"
    lease_seconds: int = 30
    delivery_ttl: timedelta = timedelta(minutes=10)
    retention: timedelta = timedelta(days=7)
    retry_delay: timedelta = timedelta(seconds=15)

    def __post_init__(self) -> None:
        if not self.worker_id or len(self.worker_id) > 256:
            raise ValueError("channel pipeline worker_id MUST be bounded and non-empty")
        if not 1 <= self.lease_seconds <= 300:
            raise ValueError("channel pipeline lease_seconds is outside the bounded range")
        if self.delivery_ttl <= timedelta(0) or self.retention < self.delivery_ttl:
            raise ValueError("channel pipeline delivery and retention windows are invalid")
        if not timedelta(0) < self.retry_delay < self.delivery_ttl:
            raise ValueError("channel pipeline retry_delay is outside the delivery window")


@dataclass(frozen=True, slots=True)
class ChannelPipelineResult:
    """Report durable ownership and current delivery state without provider content."""

    delivery_id: str
    state: ChannelDeliveryState
    duplicate: bool = False


__all__ = [
    "ChannelBindingStore",
    "ChannelDeliveryPipelineConfig",
    "ChannelDeliveryStore",
    "ChannelMessageLedger",
    "ChannelPipelineResult",
    "ChannelPrincipalContext",
    "ChannelPrincipalResolver",
    "ChannelPublisher",
]
