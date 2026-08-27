"""Durable dispatch plans and per-channel notification delivery state."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import uuid4


class ChannelDeliveryState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    RETRYABLE_FAILED = "retryable_failed"
    AMBIGUOUS = "ambiguous"
    ABANDONED = "abandoned"


class DeliveryClaimStatus(StrEnum):
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    NOT_DUE = "not_due"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class ChannelDeliveryRecord:
    channel_id: str
    state: ChannelDeliveryState
    attempts: int = 0
    provider_message_id: str | None = None
    error: str | None = None
    token: str | None = None
    lease_until: datetime | None = None
    next_attempt_at: datetime | None = None
    confirmation_deadline: datetime | None = None

    @property
    def terminal(self) -> bool:
        return self.state in {
            ChannelDeliveryState.DELIVERED,
            ChannelDeliveryState.AMBIGUOUS,
            ChannelDeliveryState.ABANDONED,
        }


@dataclass(frozen=True, slots=True)
class NotificationDispatchPlan:
    audit_id: str
    target_channel_ids: tuple[str, ...]
    excluded_channels: Mapping[str, str]
    deliveries: tuple[ChannelDeliveryRecord, ...]

    @property
    def terminal(self) -> bool:
        return bool(self.deliveries) and all(item.terminal for item in self.deliveries)


@dataclass(frozen=True, slots=True)
class ChannelDeliveryClaim:
    status: DeliveryClaimStatus
    record: ChannelDeliveryRecord


@runtime_checkable
class NotificationDeliveryStore(Protocol):
    async def create_plan(
        self,
        *,
        audit_id: str,
        target_channel_ids: tuple[str, ...],
        excluded_channels: Mapping[str, str],
        now: datetime,
    ) -> NotificationDispatchPlan: ...

    async def claim(
        self,
        *,
        audit_id: str,
        channel_id: str,
        now: datetime,
        lease_seconds: int,
        max_attempts: int,
    ) -> ChannelDeliveryClaim: ...

    async def record_result(
        self,
        *,
        audit_id: str,
        channel_id: str,
        token: str,
        state: ChannelDeliveryState,
        at: datetime,
        retry_after_seconds: float | None = None,
        confirmation_timeout_seconds: int | None = None,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> ChannelDeliveryRecord: ...

    async def confirm_delivered(
        self,
        *,
        audit_id: str,
        channel_id: str,
        at: datetime,
        provider_message_id: str | None = None,
    ) -> ChannelDeliveryRecord: ...

    async def record_publication_failure(
        self,
        *,
        audit_id: str,
        channel_id: str,
        at: datetime,
        error: str,
    ) -> ChannelDeliveryRecord: ...

    async def snapshot(
        self,
        *,
        audit_id: str,
        now: datetime,
    ) -> NotificationDispatchPlan: ...


class InMemoryNotificationDeliveryStore:
    """Lock-backed store used by local development and focused tests."""

    def __init__(self) -> None:
        self._plans: dict[str, NotificationDispatchPlan] = {}
        self._lock = asyncio.Lock()

    async def create_plan(
        self,
        *,
        audit_id: str,
        target_channel_ids: tuple[str, ...],
        excluded_channels: Mapping[str, str],
        now: datetime,
    ) -> NotificationDispatchPlan:
        _validate_identity(audit_id, now)
        if len(target_channel_ids) != len(set(target_channel_ids)):
            raise ValueError("notification target channel ids MUST be unique")
        async with self._lock:
            existing = self._plans.get(audit_id)
            if existing is not None:
                return existing
            plan = NotificationDispatchPlan(
                audit_id=audit_id,
                target_channel_ids=target_channel_ids,
                excluded_channels=dict(excluded_channels),
                deliveries=tuple(
                    ChannelDeliveryRecord(channel_id=item, state=ChannelDeliveryState.PENDING)
                    for item in target_channel_ids
                ),
            )
            self._plans[audit_id] = plan
            return plan

    async def claim(
        self,
        *,
        audit_id: str,
        channel_id: str,
        now: datetime,
        lease_seconds: int,
        max_attempts: int,
    ) -> ChannelDeliveryClaim:
        _validate_identity(audit_id, now, channel_id)
        if lease_seconds < 1 or max_attempts < 1:
            raise ValueError("notification delivery bounds MUST be positive")
        async with self._lock:
            plan = self._required_plan(audit_id)
            record = _required_delivery(plan, channel_id)
            record = _expire_accepted(record, now)
            if record.terminal:
                self._replace_record(plan, record)
                return ChannelDeliveryClaim(DeliveryClaimStatus.TERMINAL, record)
            if (
                record.state is ChannelDeliveryState.SENDING
                and record.lease_until is not None
                and record.lease_until > now
            ):
                return ChannelDeliveryClaim(DeliveryClaimStatus.IN_PROGRESS, record)
            if record.next_attempt_at is not None and record.next_attempt_at > now:
                return ChannelDeliveryClaim(DeliveryClaimStatus.NOT_DUE, record)
            if record.state is ChannelDeliveryState.ACCEPTED:
                return ChannelDeliveryClaim(DeliveryClaimStatus.NOT_DUE, record)
            if record.attempts >= max_attempts:
                abandoned = replace(
                    record,
                    state=ChannelDeliveryState.ABANDONED,
                    token=None,
                    lease_until=None,
                )
                self._replace_record(plan, abandoned)
                return ChannelDeliveryClaim(DeliveryClaimStatus.TERMINAL, abandoned)
            claimed = replace(
                record,
                state=ChannelDeliveryState.SENDING,
                attempts=record.attempts + 1,
                token=str(uuid4()),
                lease_until=now + timedelta(seconds=lease_seconds),
                next_attempt_at=None,
                error=None,
            )
            self._replace_record(plan, claimed)
            return ChannelDeliveryClaim(DeliveryClaimStatus.CLAIMED, claimed)

    async def record_result(
        self,
        *,
        audit_id: str,
        channel_id: str,
        token: str,
        state: ChannelDeliveryState,
        at: datetime,
        retry_after_seconds: float | None = None,
        confirmation_timeout_seconds: int | None = None,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> ChannelDeliveryRecord:
        _validate_identity(audit_id, at, channel_id)
        if state not in {
            ChannelDeliveryState.ACCEPTED,
            ChannelDeliveryState.DELIVERED,
            ChannelDeliveryState.RETRYABLE_FAILED,
            ChannelDeliveryState.AMBIGUOUS,
            ChannelDeliveryState.ABANDONED,
        }:
            raise ValueError("notification result state is invalid")
        if not token:
            raise ValueError("notification delivery token MUST be non-empty")
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("retry_after_seconds MUST be >= 0")
        if state is ChannelDeliveryState.ACCEPTED and (
            confirmation_timeout_seconds is None or confirmation_timeout_seconds < 1
        ):
            raise ValueError("accepted delivery requires a positive confirmation timeout")
        async with self._lock:
            plan = self._required_plan(audit_id)
            current = _required_delivery(plan, channel_id)
            if current.state is not ChannelDeliveryState.SENDING or current.token != token:
                raise RuntimeError("notification delivery claim token mismatch")
            updated = replace(
                current,
                state=state,
                provider_message_id=provider_message_id,
                error=error,
                token=None,
                lease_until=None,
                next_attempt_at=(
                    at + timedelta(seconds=retry_after_seconds)
                    if state is ChannelDeliveryState.RETRYABLE_FAILED
                    and retry_after_seconds is not None
                    else None
                ),
                confirmation_deadline=(
                    at + timedelta(seconds=confirmation_timeout_seconds)
                    if state is ChannelDeliveryState.ACCEPTED
                    and confirmation_timeout_seconds is not None
                    else None
                ),
            )
            self._replace_record(plan, updated)
            return updated

    async def confirm_delivered(
        self,
        *,
        audit_id: str,
        channel_id: str,
        at: datetime,
        provider_message_id: str | None = None,
    ) -> ChannelDeliveryRecord:
        _validate_identity(audit_id, at, channel_id)
        async with self._lock:
            plan = self._required_plan(audit_id)
            current = _required_delivery(plan, channel_id)
            if current.state is ChannelDeliveryState.DELIVERED:
                return current
            if current.state is not ChannelDeliveryState.ACCEPTED:
                raise RuntimeError("only an accepted notification delivery can be confirmed")
            updated = replace(
                current,
                state=ChannelDeliveryState.DELIVERED,
                provider_message_id=provider_message_id or current.provider_message_id,
                confirmation_deadline=None,
            )
            self._replace_record(plan, updated)
            return updated

    async def record_publication_failure(
        self,
        *,
        audit_id: str,
        channel_id: str,
        at: datetime,
        error: str,
    ) -> ChannelDeliveryRecord:
        _validate_identity(audit_id, at, channel_id)
        if not error:
            raise ValueError("publication failure error MUST be non-empty")
        async with self._lock:
            plan = self._required_plan(audit_id)
            current = _required_delivery(plan, channel_id)
            if current.state is ChannelDeliveryState.RETRYABLE_FAILED:
                return current
            if current.state is not ChannelDeliveryState.ACCEPTED:
                raise RuntimeError("only an accepted notification delivery can report failure")
            updated = replace(
                current,
                state=ChannelDeliveryState.RETRYABLE_FAILED,
                error=error,
                confirmation_deadline=None,
                next_attempt_at=at,
            )
            self._replace_record(plan, updated)
            return updated

    async def snapshot(
        self,
        *,
        audit_id: str,
        now: datetime,
    ) -> NotificationDispatchPlan:
        _validate_identity(audit_id, now)
        async with self._lock:
            plan = self._required_plan(audit_id)
            for record in plan.deliveries:
                self._replace_record(plan, _expire_accepted(record, now))
                plan = self._required_plan(audit_id)
            return plan

    def _required_plan(self, audit_id: str) -> NotificationDispatchPlan:
        try:
            return self._plans[audit_id]
        except KeyError as exc:
            raise KeyError(f"notification dispatch plan {audit_id!r} does not exist") from exc

    def _replace_record(
        self,
        plan: NotificationDispatchPlan,
        updated: ChannelDeliveryRecord,
    ) -> None:
        self._plans[plan.audit_id] = replace(
            plan,
            deliveries=tuple(
                updated if item.channel_id == updated.channel_id else item
                for item in plan.deliveries
            ),
        )


def _required_delivery(
    plan: NotificationDispatchPlan,
    channel_id: str,
) -> ChannelDeliveryRecord:
    for item in plan.deliveries:
        if item.channel_id == channel_id:
            return item
    raise KeyError(f"channel {channel_id!r} is not part of notification dispatch {plan.audit_id!r}")


def _expire_accepted(record: ChannelDeliveryRecord, now: datetime) -> ChannelDeliveryRecord:
    if (
        record.state is ChannelDeliveryState.ACCEPTED
        and record.confirmation_deadline is not None
        and record.confirmation_deadline <= now
    ):
        return replace(
            record,
            state=ChannelDeliveryState.AMBIGUOUS,
            confirmation_deadline=None,
            error="publication confirmation deadline expired",
        )
    return record


def _validate_identity(audit_id: str, at: datetime, channel_id: str | None = None) -> None:
    if not audit_id:
        raise ValueError("notification audit_id MUST be non-empty")
    if channel_id is not None and not channel_id:
        raise ValueError("notification channel_id MUST be non-empty")
    if at.tzinfo is None:
        raise ValueError("notification timestamp MUST be timezone-aware")


__all__ = [
    "ChannelDeliveryClaim",
    "ChannelDeliveryRecord",
    "ChannelDeliveryState",
    "DeliveryClaimStatus",
    "InMemoryNotificationDeliveryStore",
    "NotificationDeliveryStore",
    "NotificationDispatchPlan",
]
