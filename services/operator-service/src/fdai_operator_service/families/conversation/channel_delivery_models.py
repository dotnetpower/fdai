"""Define Operator-owned durable channel binding and delivery records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fdai_operator_service.families.conversation.contracts import JsonObject

MAX_DELIVERY_ATTEMPTS = 8
MAX_DELIVERY_LEASE_SECONDS = 300


class ChannelKind(StrEnum):
    """Supported durable conversation channels."""

    WEB = "web"
    SLACK = "slack"
    TEAMS = "teams"


class ChannelBindingState(StrEnum):
    """Lifecycle of one verified principal-to-provider endpoint binding."""

    ACTIVE = "active"
    REVOKED = "revoked"


class ChannelDeliveryState(StrEnum):
    """Lease-fenced outbound delivery state."""

    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"
    ABANDONED = "abandoned"

    @property
    def immutable(self) -> bool:
        """Return whether the database must reject every later state update."""
        return self in {self.DELIVERED, self.AMBIGUOUS, self.ABANDONED}


class ChannelBreakerMode(StrEnum):
    """Operator-controlled provider-adapter admission mode."""

    CLOSED = "closed"
    OPEN = "open"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class VerifiedChannelEndpoint:
    """Keep canonical principal identity separate from vendor routing identity."""

    principal_id: str
    scope_ref: str
    channel_kind: ChannelKind
    channel_id: str
    sender_id: str
    thread_id: str | None
    verification_ref: str
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class PrincipalChannelBinding:
    """Persist one verified endpoint for a principal-scoped conversation."""

    binding_id: str
    principal_id: str
    scope_ref: str
    conversation_id: str
    endpoint: VerifiedChannelEndpoint
    created_by: str
    created_at: datetime
    resumed_from_binding_id: str | None = None
    state: ChannelBindingState = ChannelBindingState.ACTIVE
    revoked_by: str | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.endpoint.principal_id != self.principal_id:
            raise ValueError("binding endpoint principal MUST match binding principal")
        if self.endpoint.scope_ref != self.scope_ref:
            raise ValueError("binding endpoint scope MUST match binding scope")
        revoked = self.state is ChannelBindingState.REVOKED
        if revoked != (self.revoked_by is not None and self.revoked_at is not None):
            raise ValueError("binding revocation fields MUST match binding state")


@dataclass(frozen=True, slots=True)
class ChannelDeliveryRecord:
    """Persist one immutable semantic terminal response before provider I/O."""

    delivery_id: str
    idempotency_key: str
    principal_id: str
    scope_ref: str
    conversation_id: str
    binding_id: str | None
    channel_kind: ChannelKind
    response: JsonObject
    response_digest: str
    state: ChannelDeliveryState
    created_at: datetime
    due_at: datetime
    expires_at: datetime
    retention_until: datetime
    attempt_count: int = 0
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_error_code: str | None = None
    duplicate_risk: bool = False
    terminal_at: datetime | None = None

    def __post_init__(self) -> None:
        if channel_response_digest(self.response) != self.response_digest:
            raise ValueError("channel delivery response digest does not match response")
        if not self.created_at <= self.due_at < self.expires_at <= self.retention_until:
            raise ValueError("channel delivery times are not ordered")
        if not 0 <= self.attempt_count <= MAX_DELIVERY_ATTEMPTS:
            raise ValueError("channel delivery attempt_count is outside the bounded range")
        sending = self.state is ChannelDeliveryState.SENDING
        if sending != (self.lease_owner is not None and self.lease_expires_at is not None):
            raise ValueError("channel delivery lease fields MUST match sending state")
        if self.state.immutable != (self.terminal_at is not None):
            raise ValueError("channel delivery terminal_at MUST match terminal state")
        if self.state is ChannelDeliveryState.AMBIGUOUS and not self.duplicate_risk:
            raise ValueError("ambiguous channel delivery MUST report duplicate risk")


@dataclass(frozen=True, slots=True)
class ChannelDeliveryAttempt:
    """Persist one provider-send attempt for a claimed delivery."""

    attempt_id: str
    delivery_id: str
    sequence: int
    worker_id: str
    started_at: datetime
    completed_at: datetime | None = None
    outcome: ChannelDeliveryState | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ChannelDeliveryAcknowledgement:
    """Persist one definitive provider acknowledgement for a delivered record."""

    delivery_id: str
    attempt_id: str
    provider_message_id: str
    acknowledged_at: datetime
    degraded_to_text: bool = False


@dataclass(frozen=True, slots=True)
class ChannelAdapterBreaker:
    """Persist revision-fenced provider-adapter admission state."""

    adapter_id: str
    channel_kind: ChannelKind
    mode: ChannelBreakerMode
    failure_timestamps: tuple[datetime, ...] = field(default_factory=tuple)
    revision: int = 0
    updated_at: datetime | None = None
    updated_by: str = "system"
    reason: str = "initialized"

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("channel adapter breaker revision MUST be non-negative")
        if self.updated_at is None:
            raise ValueError("channel adapter breaker updated_at MUST be set")
        if not self.reason or len(self.reason) > 512:
            raise ValueError("channel adapter breaker reason MUST be bounded")


@dataclass(frozen=True, slots=True)
class ChannelDeliverySnapshot:
    """Bound one operational read of deliveries, attempts, acks, and breakers."""

    deliveries: tuple[ChannelDeliveryRecord, ...] = ()
    attempts: tuple[ChannelDeliveryAttempt, ...] = ()
    acknowledgements: tuple[ChannelDeliveryAcknowledgement, ...] = ()
    breakers: tuple[ChannelAdapterBreaker, ...] = ()


def channel_response_digest(response: JsonObject) -> str:
    """Return the stable SHA-256 digest for one bounded semantic response object."""
    encoded = json.dumps(
        response,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ChannelAdapterBreaker",
    "ChannelBindingState",
    "ChannelBreakerMode",
    "ChannelDeliveryAcknowledgement",
    "ChannelDeliveryAttempt",
    "ChannelDeliveryRecord",
    "ChannelDeliverySnapshot",
    "ChannelDeliveryState",
    "ChannelKind",
    "MAX_DELIVERY_ATTEMPTS",
    "MAX_DELIVERY_LEASE_SECONDS",
    "PrincipalChannelBinding",
    "VerifiedChannelEndpoint",
    "channel_response_digest",
]
