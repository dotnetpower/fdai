"""Durable principal binding and outbound conversation delivery contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    OutboundResponse,
    outbound_response_from_json,
    outbound_response_to_json,
)

MAX_DELIVERY_ATTEMPTS = 8
MAX_DELIVERY_ERROR_CHARS = 512
MAX_DELIVERY_LEASE_SECONDS = 300


class PrincipalConversationBindingState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class VerifiedChannelEndpoint:
    """Canonical principal mapping verified before it reaches the binding service."""

    principal_id: str
    scope_ref: str
    channel_kind: ConversationChannelKind
    channel_id: str
    sender_id: str
    thread_id: str | None
    verification_ref: str
    verified_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("principal_id", self.principal_id),
            ("scope_ref", self.scope_ref),
            ("channel_id", self.channel_id),
            ("sender_id", self.sender_id),
            ("verification_ref", self.verification_ref),
        ):
            _identifier(name, value)
        if self.thread_id is not None:
            _identifier("thread_id", self.thread_id)
        _aware("verified_at", self.verified_at)


@dataclass(frozen=True, slots=True)
class PrincipalConversationBinding:
    binding_id: str
    principal_id: str
    scope_ref: str
    conversation_id: str
    endpoint: VerifiedChannelEndpoint
    created_by: str
    created_at: datetime
    resumed_from_binding_id: str | None = None
    state: PrincipalConversationBindingState = PrincipalConversationBindingState.ACTIVE
    revoked_by: str | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("binding_id", self.binding_id),
            ("principal_id", self.principal_id),
            ("scope_ref", self.scope_ref),
            ("conversation_id", self.conversation_id),
            ("created_by", self.created_by),
        ):
            _identifier(name, value)
        if self.endpoint.principal_id != self.principal_id:
            raise ValueError("binding endpoint principal MUST match principal_id")
        if self.endpoint.scope_ref != self.scope_ref:
            raise ValueError("binding endpoint scope MUST match scope_ref")
        if self.resumed_from_binding_id is not None:
            _identifier("resumed_from_binding_id", self.resumed_from_binding_id)
        _aware("created_at", self.created_at)
        if self.state is PrincipalConversationBindingState.ACTIVE:
            if self.revoked_by is not None or self.revoked_at is not None:
                raise ValueError("active binding cannot carry revocation metadata")
        elif self.revoked_by is None or self.revoked_at is None:
            raise ValueError("revoked binding MUST carry actor and timestamp")


class OutboundDeliveryState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"
    ABANDONED = "abandoned"

    @property
    def immutable(self) -> bool:
        return self in {
            OutboundDeliveryState.DELIVERED,
            OutboundDeliveryState.AMBIGUOUS,
            OutboundDeliveryState.ABANDONED,
        }


class AdapterBreakerMode(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class OutboundDeliveryRecord:
    delivery_id: str
    idempotency_key: str
    principal_id: str
    scope_ref: str
    conversation_id: str
    binding_id: str | None
    response: OutboundResponse
    response_digest: str
    state: OutboundDeliveryState
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
        for name, value in (
            ("delivery_id", self.delivery_id),
            ("idempotency_key", self.idempotency_key),
            ("principal_id", self.principal_id),
            ("scope_ref", self.scope_ref),
            ("conversation_id", self.conversation_id),
        ):
            _identifier(name, value)
        if self.binding_id is not None:
            _identifier("binding_id", self.binding_id)
        if self.response_digest != response_digest(self.response):
            raise ValueError("delivery response_digest does not match response")
        if not 0 <= self.attempt_count <= MAX_DELIVERY_ATTEMPTS:
            raise ValueError("delivery attempt_count is outside the bounded range")
        for timestamp_name, timestamp_value in (
            ("created_at", self.created_at),
            ("due_at", self.due_at),
            ("expires_at", self.expires_at),
            ("retention_until", self.retention_until),
        ):
            _aware(timestamp_name, timestamp_value)
        if not self.created_at <= self.due_at < self.expires_at <= self.retention_until:
            raise ValueError("delivery timestamps are not ordered")
        if self.state is OutboundDeliveryState.SENDING:
            if self.lease_owner is None or self.lease_expires_at is None:
                raise ValueError("sending delivery MUST carry a lease")
        elif self.lease_owner is not None or self.lease_expires_at is not None:
            raise ValueError("only sending delivery can carry a lease")
        if self.state.immutable != (self.terminal_at is not None):
            raise ValueError("immutable terminal delivery MUST carry terminal_at")
        if self.state is OutboundDeliveryState.AMBIGUOUS and not self.duplicate_risk:
            raise ValueError("ambiguous delivery MUST expose duplicate risk")
        if self.last_error_code is not None:
            _bounded("last_error_code", self.last_error_code, MAX_DELIVERY_ERROR_CHARS)


@dataclass(frozen=True, slots=True)
class OutboundDeliveryAttempt:
    attempt_id: str
    delivery_id: str
    sequence: int
    worker_id: str
    started_at: datetime
    completed_at: datetime | None = None
    outcome: OutboundDeliveryState | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class OutboundDeliveryAcknowledgement:
    delivery_id: str
    attempt_id: str
    provider_message_id: str
    acknowledged_at: datetime
    degraded_to_text: bool = False


@dataclass(frozen=True, slots=True)
class AdapterBreakerRecord:
    adapter_id: str
    channel_kind: ConversationChannelKind
    mode: AdapterBreakerMode
    failure_timestamps: tuple[datetime, ...]
    revision: int
    updated_at: datetime
    updated_by: str
    reason: str


@dataclass(frozen=True, slots=True)
class ConversationDeliverySnapshot:
    deliveries: tuple[OutboundDeliveryRecord, ...]
    attempts: tuple[OutboundDeliveryAttempt, ...]
    acknowledgements: tuple[OutboundDeliveryAcknowledgement, ...]
    breakers: tuple[AdapterBreakerRecord, ...]


class ConversationDeliveryStore(Protocol):
    async def put(self, record: OutboundDeliveryRecord) -> OutboundDeliveryRecord: ...

    async def get(self, delivery_id: str) -> OutboundDeliveryRecord | None: ...

    async def claim(
        self,
        *,
        delivery_id: str,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> OutboundDeliveryRecord | None: ...

    async def claim_due(
        self,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
        limit: int,
    ) -> tuple[OutboundDeliveryRecord, ...]: ...

    async def finish(
        self,
        *,
        delivery_id: str,
        worker_id: str,
        expected_attempt_count: int,
        state: OutboundDeliveryState,
        at: datetime,
        next_due_at: datetime | None = None,
        error_code: str | None = None,
        acknowledgement: OutboundDeliveryAcknowledgement | None = None,
    ) -> OutboundDeliveryRecord: ...

    async def reconcile_sending(self, *, now: datetime) -> int: ...

    async def snapshot(self, *, limit: int = 200) -> ConversationDeliverySnapshot: ...

    async def get_breaker(self, adapter_id: str) -> AdapterBreakerRecord | None: ...

    async def put_breaker(
        self,
        record: AdapterBreakerRecord,
        *,
        expected_revision: int | None,
    ) -> AdapterBreakerRecord: ...


class InMemoryConversationDeliveryStore:
    """Deterministic test/default store with the same CAS rules as PostgreSQL."""

    def __init__(self) -> None:
        self._records: dict[str, OutboundDeliveryRecord] = {}
        self._idempotency: dict[str, str] = {}
        self._attempts: list[OutboundDeliveryAttempt] = []
        self._acknowledgements: list[OutboundDeliveryAcknowledgement] = []
        self._breakers: dict[str, AdapterBreakerRecord] = {}

    async def put(self, record: OutboundDeliveryRecord) -> OutboundDeliveryRecord:
        existing_id = self._idempotency.get(record.idempotency_key)
        if existing_id is not None:
            existing = self._records[existing_id]
            if existing.response_digest != record.response_digest:
                raise ValueError("delivery idempotency key was reused with different response")
            return existing
        if record.delivery_id in self._records:
            raise ValueError("delivery_id already exists")
        self._records[record.delivery_id] = record
        self._idempotency[record.idempotency_key] = record.delivery_id
        return record

    async def get(self, delivery_id: str) -> OutboundDeliveryRecord | None:
        return self._records.get(delivery_id)

    async def claim(
        self,
        *,
        delivery_id: str,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> OutboundDeliveryRecord | None:
        if not 1 <= lease_seconds <= MAX_DELIVERY_LEASE_SECONDS:
            raise ValueError("delivery lease_seconds is invalid")
        current = self._records.get(delivery_id)
        if current is None:
            return None
        return self._claim_current(
            current,
            now=now,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )

    async def claim_due(
        self,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
        limit: int,
    ) -> tuple[OutboundDeliveryRecord, ...]:
        if not 1 <= lease_seconds <= MAX_DELIVERY_LEASE_SECONDS or not 1 <= limit <= 200:
            raise ValueError("delivery claim bounds are invalid")
        claimed: list[OutboundDeliveryRecord] = []
        for current in sorted(
            self._records.values(),
            key=lambda item: (item.due_at, item.delivery_id),
        ):
            if len(claimed) >= limit:
                break
            claimed_record = self._claim_current(
                current,
                now=now,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
            if claimed_record is not None:
                claimed.append(claimed_record)
        return tuple(claimed)

    async def finish(
        self,
        *,
        delivery_id: str,
        worker_id: str,
        expected_attempt_count: int,
        state: OutboundDeliveryState,
        at: datetime,
        next_due_at: datetime | None = None,
        error_code: str | None = None,
        acknowledgement: OutboundDeliveryAcknowledgement | None = None,
    ) -> OutboundDeliveryRecord:
        current = self._records.get(delivery_id)
        if current is None:
            raise KeyError(delivery_id)
        if current.state.immutable:
            raise ValueError("terminal delivery state is immutable")
        if (
            current.state is not OutboundDeliveryState.SENDING
            or current.lease_owner != worker_id
            or current.attempt_count != expected_attempt_count
        ):
            raise ValueError("delivery lease compare-and-set failed")
        if state not in {
            OutboundDeliveryState.DELIVERED,
            OutboundDeliveryState.AMBIGUOUS,
            OutboundDeliveryState.FAILED,
            OutboundDeliveryState.ABANDONED,
        }:
            raise ValueError("sending delivery has an invalid completion state")
        if state is OutboundDeliveryState.FAILED:
            if next_due_at is None or not current.due_at <= next_due_at < current.expires_at:
                raise ValueError("failed delivery MUST carry a bounded retry time")
        elif next_due_at is not None:
            raise ValueError("only failed delivery can carry next_due_at")
        terminal_at = at if state.immutable else None
        updated = replace(
            current,
            state=state,
            due_at=next_due_at or current.due_at,
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=error_code,
            duplicate_risk=state is OutboundDeliveryState.AMBIGUOUS,
            terminal_at=terminal_at,
        )
        self._records[delivery_id] = updated
        attempt_id = _attempt_id(delivery_id, expected_attempt_count)
        for index, attempt in enumerate(self._attempts):
            if attempt.attempt_id == attempt_id:
                self._attempts[index] = replace(
                    attempt,
                    completed_at=at,
                    outcome=state,
                    error_code=error_code,
                )
                break
        if acknowledgement is not None:
            if state is not OutboundDeliveryState.DELIVERED:
                raise ValueError("only delivered state can persist acknowledgement")
            self._acknowledgements.append(acknowledgement)
        return updated

    async def reconcile_sending(self, *, now: datetime) -> int:
        reconciled = 0
        for delivery_id, current in tuple(self._records.items()):
            if (
                current.state is OutboundDeliveryState.SENDING
                and current.lease_expires_at is not None
                and current.lease_expires_at <= now
            ):
                self._records[delivery_id] = replace(
                    current,
                    state=OutboundDeliveryState.AMBIGUOUS,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code="process_loss",
                    duplicate_risk=True,
                    terminal_at=now,
                )
                reconciled += 1
        return reconciled

    async def snapshot(self, *, limit: int = 200) -> ConversationDeliverySnapshot:
        if not 1 <= limit <= 500:
            raise ValueError("delivery snapshot limit is invalid")
        records = sorted(self._records.values(), key=lambda item: item.created_at, reverse=True)
        return ConversationDeliverySnapshot(
            deliveries=tuple(records[:limit]),
            attempts=tuple(self._attempts[-limit:]),
            acknowledgements=tuple(self._acknowledgements[-limit:]),
            breakers=tuple(self._breakers.values()),
        )

    async def get_breaker(self, adapter_id: str) -> AdapterBreakerRecord | None:
        return self._breakers.get(adapter_id)

    async def put_breaker(
        self,
        record: AdapterBreakerRecord,
        *,
        expected_revision: int | None,
    ) -> AdapterBreakerRecord:
        current = self._breakers.get(record.adapter_id)
        current_revision = current.revision if current is not None else None
        if current_revision != expected_revision:
            raise ValueError("adapter breaker compare-and-set failed")
        self._breakers[record.adapter_id] = record
        return record

    def _claim_current(
        self,
        current: OutboundDeliveryRecord,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> OutboundDeliveryRecord | None:
        if current.state not in {OutboundDeliveryState.PENDING, OutboundDeliveryState.FAILED}:
            return None
        if current.due_at > now or current.expires_at <= now:
            return None
        attempt_count = current.attempt_count + 1
        if attempt_count > MAX_DELIVERY_ATTEMPTS:
            return None
        claimed_record = replace(
            current,
            state=OutboundDeliveryState.SENDING,
            attempt_count=attempt_count,
            lease_owner=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            last_error_code=None,
        )
        self._records[current.delivery_id] = claimed_record
        self._attempts.append(
            OutboundDeliveryAttempt(
                attempt_id=_attempt_id(current.delivery_id, attempt_count),
                delivery_id=current.delivery_id,
                sequence=attempt_count,
                worker_id=worker_id,
                started_at=now,
            )
        )
        return claimed_record


def response_digest(response: OutboundResponse) -> str:
    payload = json.dumps(
        outbound_response_to_json(response),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def delivery_idempotency_key(*, origin_ref: str, response: OutboundResponse) -> str:
    _identifier("origin_ref", origin_ref)
    raw = "\0".join(
        (
            origin_ref,
            response.channel_kind.value,
            response.channel_id,
            response.in_reply_to,
            response.thread_id or "",
            response.operation.value,
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def new_delivery_record(
    *,
    origin_ref: str,
    principal_id: str,
    scope_ref: str,
    conversation_id: str,
    binding_id: str | None,
    response: OutboundResponse,
    created_at: datetime,
    freshness: timedelta,
    retention: timedelta,
) -> OutboundDeliveryRecord:
    if freshness <= timedelta(0) or retention < freshness:
        raise ValueError("delivery freshness and retention are invalid")
    key = delivery_idempotency_key(origin_ref=origin_ref, response=response)
    return OutboundDeliveryRecord(
        delivery_id=f"delivery:{key[:40]}",
        idempotency_key=key,
        principal_id=principal_id,
        scope_ref=scope_ref,
        conversation_id=conversation_id,
        binding_id=binding_id,
        response=response,
        response_digest=response_digest(response),
        state=OutboundDeliveryState.PENDING,
        created_at=created_at,
        due_at=created_at,
        expires_at=created_at + freshness,
        retention_until=created_at + retention,
    )


def delivery_record_to_json(record: OutboundDeliveryRecord) -> dict[str, Any]:
    return {
        "delivery_id": record.delivery_id,
        "idempotency_key": record.idempotency_key,
        "principal_id": record.principal_id,
        "scope_ref": record.scope_ref,
        "conversation_id": record.conversation_id,
        "binding_id": record.binding_id,
        "response": outbound_response_to_json(record.response),
        "response_digest": record.response_digest,
        "state": record.state.value,
        "created_at": record.created_at.isoformat(),
        "due_at": record.due_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "retention_until": record.retention_until.isoformat(),
        "attempt_count": record.attempt_count,
        "lease_owner": record.lease_owner,
        "lease_expires_at": (
            record.lease_expires_at.isoformat() if record.lease_expires_at is not None else None
        ),
        "last_error_code": record.last_error_code,
        "duplicate_risk": record.duplicate_risk,
        "terminal_at": record.terminal_at.isoformat() if record.terminal_at is not None else None,
    }


def delivery_record_from_json(value: dict[str, Any]) -> OutboundDeliveryRecord:
    return OutboundDeliveryRecord(
        delivery_id=str(value["delivery_id"]),
        idempotency_key=str(value["idempotency_key"]),
        principal_id=str(value["principal_id"]),
        scope_ref=str(value["scope_ref"]),
        conversation_id=str(value["conversation_id"]),
        binding_id=str(value["binding_id"]) if value.get("binding_id") is not None else None,
        response=outbound_response_from_json(value["response"]),
        response_digest=str(value["response_digest"]),
        state=OutboundDeliveryState(str(value["state"])),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        due_at=datetime.fromisoformat(str(value["due_at"])),
        expires_at=datetime.fromisoformat(str(value["expires_at"])),
        retention_until=datetime.fromisoformat(str(value["retention_until"])),
        attempt_count=int(value["attempt_count"]),
        lease_owner=str(value["lease_owner"]) if value.get("lease_owner") is not None else None,
        lease_expires_at=(
            datetime.fromisoformat(str(value["lease_expires_at"]))
            if value.get("lease_expires_at") is not None
            else None
        ),
        last_error_code=(
            str(value["last_error_code"]) if value.get("last_error_code") is not None else None
        ),
        duplicate_risk=bool(value["duplicate_risk"]),
        terminal_at=(
            datetime.fromisoformat(str(value["terminal_at"]))
            if value.get("terminal_at") is not None
            else None
        ),
    )


def _attempt_id(delivery_id: str, sequence: int) -> str:
    return f"{delivery_id}:attempt:{sequence}"


def _identifier(name: str, value: str) -> None:
    _bounded(name, value, 512)
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} contains control characters")


def _bounded(name: str, value: str, maximum: int) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} MUST be bounded non-empty text")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "AdapterBreakerMode",
    "AdapterBreakerRecord",
    "ConversationDeliverySnapshot",
    "ConversationDeliveryStore",
    "InMemoryConversationDeliveryStore",
    "MAX_DELIVERY_ATTEMPTS",
    "OutboundDeliveryAcknowledgement",
    "OutboundDeliveryAttempt",
    "OutboundDeliveryRecord",
    "OutboundDeliveryState",
    "PrincipalConversationBinding",
    "PrincipalConversationBindingState",
    "VerifiedChannelEndpoint",
    "delivery_idempotency_key",
    "delivery_record_from_json",
    "delivery_record_to_json",
    "new_delivery_record",
    "response_digest",
]
