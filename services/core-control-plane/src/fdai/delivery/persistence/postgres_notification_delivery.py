"""PostgreSQL dispatch plans and per-channel notification delivery records."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from fdai.core.notifications.delivery import (
    ChannelDeliveryClaim,
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    DeliveryClaimStatus,
    NotificationDispatchPlan,
)
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig

_DISPATCH_PREFIX = "notification-dispatch:"
_DELIVERY_PREFIX = "notification-delivery:"


class PostgresNotificationDeliveryStore:
    """Persist one immutable target snapshot and one mutable row per target."""

    def __init__(self, *, config: PostgresStateStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresStateStoreConfig.dsn MUST NOT be empty")
        self._config = config

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        for delay in (0.5, 1.0):
            try:
                return await psycopg.AsyncConnection.connect(
                    self._config.dsn,
                    row_factory=dict_row,
                    connect_timeout=self._config.connect_timeout_s,
                )
            except psycopg.OperationalError:
                await asyncio.sleep(delay)
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

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
        async with await self._connect() as connection:
            async with connection.transaction():
                await _timeout(connection, self._config.statement_timeout_ms)
                await connection.execute(
                    """
                    INSERT INTO state_kv (key, value)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    (
                        _dispatch_key(audit_id),
                        json.dumps(
                            {
                                "audit_id": audit_id,
                                "target_channel_ids": list(target_channel_ids),
                                "excluded_channels": dict(excluded_channels),
                                "created_at": now.isoformat(),
                            }
                        ),
                    ),
                )
                plan_row = await _fetch_required(
                    connection,
                    "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                    (_dispatch_key(audit_id),),
                    "notification dispatch plan disappeared",
                )
                plan_value = _mapping(plan_row["value"], "notification dispatch plan")
                frozen_targets = _string_tuple(
                    plan_value.get("target_channel_ids"),
                    "target_channel_ids",
                )
                for channel_id in frozen_targets:
                    await connection.execute(
                        """
                        INSERT INTO state_kv (key, value)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (key) DO NOTHING
                        """,
                        (
                            _delivery_key(audit_id, channel_id),
                            json.dumps(
                                {
                                    "audit_id": audit_id,
                                    "channel_id": channel_id,
                                    "state": ChannelDeliveryState.PENDING.value,
                                    "attempts": 0,
                                }
                            ),
                        ),
                    )
                return await self._snapshot(connection, audit_id, now)

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
        async with await self._connect() as connection:
            async with connection.transaction():
                await _timeout(connection, self._config.statement_timeout_ms)
                row = await _fetch_required(
                    connection,
                    "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                    (_delivery_key(audit_id, channel_id),),
                    "notification delivery record does not exist",
                )
                record = _delivery_record(row["value"])
                record = _expire_accepted(record, now)
                if record.terminal:
                    await _write_record(connection, audit_id, record)
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
                    abandoned = ChannelDeliveryRecord(
                        channel_id=channel_id,
                        state=ChannelDeliveryState.ABANDONED,
                        attempts=record.attempts,
                        provider_message_id=record.provider_message_id,
                        error=record.error,
                    )
                    await _write_record(connection, audit_id, abandoned)
                    return ChannelDeliveryClaim(DeliveryClaimStatus.TERMINAL, abandoned)
                claimed = ChannelDeliveryRecord(
                    channel_id=channel_id,
                    state=ChannelDeliveryState.SENDING,
                    attempts=record.attempts + 1,
                    provider_message_id=record.provider_message_id,
                    token=str(uuid4()),
                    lease_until=now + timedelta(seconds=lease_seconds),
                )
                await _write_record(connection, audit_id, claimed)
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
        async with await self._connect() as connection:
            async with connection.transaction():
                await _timeout(connection, self._config.statement_timeout_ms)
                row = await _fetch_required(
                    connection,
                    "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                    (_delivery_key(audit_id, channel_id),),
                    "notification delivery record does not exist",
                )
                current = _delivery_record(row["value"])
                if current.state is not ChannelDeliveryState.SENDING or current.token != token:
                    raise RuntimeError("notification delivery claim token mismatch")
                updated = ChannelDeliveryRecord(
                    channel_id=channel_id,
                    state=state,
                    attempts=current.attempts,
                    provider_message_id=provider_message_id,
                    error=error,
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
                await _write_record(connection, audit_id, updated)
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
        async with await self._connect() as connection:
            async with connection.transaction():
                await _timeout(connection, self._config.statement_timeout_ms)
                row = await _fetch_required(
                    connection,
                    "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                    (_delivery_key(audit_id, channel_id),),
                    "notification delivery record does not exist",
                )
                current = _delivery_record(row["value"])
                if current.state is ChannelDeliveryState.DELIVERED:
                    return current
                if current.state is not ChannelDeliveryState.ACCEPTED:
                    raise RuntimeError("only an accepted notification delivery can be confirmed")
                updated = ChannelDeliveryRecord(
                    channel_id=channel_id,
                    state=ChannelDeliveryState.DELIVERED,
                    attempts=current.attempts,
                    provider_message_id=provider_message_id or current.provider_message_id,
                )
                await _write_record(connection, audit_id, updated)
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
        async with await self._connect() as connection:
            async with connection.transaction():
                await _timeout(connection, self._config.statement_timeout_ms)
                row = await _fetch_required(
                    connection,
                    "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                    (_delivery_key(audit_id, channel_id),),
                    "notification delivery record does not exist",
                )
                current = _delivery_record(row["value"])
                if current.state is ChannelDeliveryState.RETRYABLE_FAILED:
                    return current
                if current.state is not ChannelDeliveryState.ACCEPTED:
                    raise RuntimeError("only an accepted notification delivery can report failure")
                updated = ChannelDeliveryRecord(
                    channel_id=channel_id,
                    state=ChannelDeliveryState.RETRYABLE_FAILED,
                    attempts=current.attempts,
                    provider_message_id=current.provider_message_id,
                    error=error,
                    next_attempt_at=at,
                )
                await _write_record(connection, audit_id, updated)
                return updated

    async def snapshot(
        self,
        *,
        audit_id: str,
        now: datetime,
    ) -> NotificationDispatchPlan:
        _validate_identity(audit_id, now)
        async with await self._connect() as connection:
            async with connection.transaction():
                await _timeout(connection, self._config.statement_timeout_ms)
                return await self._snapshot(connection, audit_id, now)

    async def _snapshot(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        audit_id: str,
        now: datetime,
    ) -> NotificationDispatchPlan:
        row = await _fetch_required(
            connection,
            "SELECT value FROM state_kv WHERE key = %s",
            (_dispatch_key(audit_id),),
            "notification dispatch plan does not exist",
        )
        value = _mapping(row["value"], "notification dispatch plan")
        targets = _string_tuple(value.get("target_channel_ids"), "target_channel_ids")
        excluded = _string_mapping(value.get("excluded_channels"), "excluded_channels")
        deliveries: list[ChannelDeliveryRecord] = []
        for channel_id in targets:
            delivery_row = await _fetch_required(
                connection,
                "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                (_delivery_key(audit_id, channel_id),),
                "notification delivery record does not exist",
            )
            record = _expire_accepted(_delivery_record(delivery_row["value"]), now)
            await _write_record(connection, audit_id, record)
            deliveries.append(record)
        return NotificationDispatchPlan(
            audit_id=audit_id,
            target_channel_ids=targets,
            excluded_channels=excluded,
            deliveries=tuple(deliveries),
        )


def _dispatch_key(audit_id: str) -> str:
    return f"{_DISPATCH_PREFIX}{hashlib.sha256(audit_id.encode()).hexdigest()}"


def _delivery_key(audit_id: str, channel_id: str) -> str:
    material = f"{audit_id}\0{channel_id}".encode()
    return f"{_DELIVERY_PREFIX}{hashlib.sha256(material).hexdigest()}"


def _record_value(audit_id: str, record: ChannelDeliveryRecord) -> dict[str, object]:
    return {
        "audit_id": audit_id,
        "channel_id": record.channel_id,
        "state": record.state.value,
        "attempts": record.attempts,
        "provider_message_id": record.provider_message_id,
        "error": record.error,
        "token": record.token,
        "lease_until": _time_value(record.lease_until),
        "next_attempt_at": _time_value(record.next_attempt_at),
        "confirmation_deadline": _time_value(record.confirmation_deadline),
    }


async def _write_record(
    connection: psycopg.AsyncConnection[dict[str, Any]],
    audit_id: str,
    record: ChannelDeliveryRecord,
) -> None:
    cursor = await connection.execute(
        "UPDATE state_kv SET value = %s::jsonb, updated_at = NOW() WHERE key = %s",
        (json.dumps(_record_value(audit_id, record)), _delivery_key(audit_id, record.channel_id)),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("notification delivery record disappeared")


def _delivery_record(value: object) -> ChannelDeliveryRecord:
    record = _mapping(value, "notification delivery")
    channel_id = record.get("channel_id")
    attempts = record.get("attempts")
    state = record.get("state")
    if not isinstance(channel_id, str) or not channel_id:
        raise RuntimeError("notification delivery channel_id is invalid")
    if not isinstance(attempts, int) or attempts < 0:
        raise RuntimeError("notification delivery attempts is invalid")
    if not isinstance(state, str):
        raise RuntimeError("notification delivery state is invalid")
    try:
        parsed_state = ChannelDeliveryState(state)
    except ValueError as exc:
        raise RuntimeError("notification delivery state is invalid") from exc
    return ChannelDeliveryRecord(
        channel_id=channel_id,
        state=parsed_state,
        attempts=attempts,
        provider_message_id=_optional_string(record.get("provider_message_id")),
        error=_optional_string(record.get("error")),
        token=_optional_string(record.get("token")),
        lease_until=_optional_time(record.get("lease_until"), "lease_until"),
        next_attempt_at=_optional_time(record.get("next_attempt_at"), "next_attempt_at"),
        confirmation_deadline=_optional_time(
            record.get("confirmation_deadline"),
            "confirmation_deadline",
        ),
    )


def _expire_accepted(record: ChannelDeliveryRecord, now: datetime) -> ChannelDeliveryRecord:
    if (
        record.state is ChannelDeliveryState.ACCEPTED
        and record.confirmation_deadline is not None
        and record.confirmation_deadline <= now
    ):
        return ChannelDeliveryRecord(
            channel_id=record.channel_id,
            state=ChannelDeliveryState.AMBIGUOUS,
            attempts=record.attempts,
            provider_message_id=record.provider_message_id,
            error="publication confirmation deadline expired",
        )
    return record


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} value is not a JSON object")
    return dict(value)


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RuntimeError(f"notification dispatch {field} is invalid")
    return tuple(value)


def _string_mapping(value: object, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and key and isinstance(item, str) and item
        for key, item in value.items()
    ):
        raise RuntimeError(f"notification dispatch {field} is invalid")
    return dict(value)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError("notification delivery optional string is invalid")
    return value


def _optional_time(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"notification delivery {field} is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise RuntimeError(f"notification delivery {field} is timezone-naive")
    return parsed


def _time_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _validate_identity(audit_id: str, at: datetime, channel_id: str | None = None) -> None:
    if not audit_id:
        raise ValueError("notification audit_id MUST be non-empty")
    if channel_id is not None and not channel_id:
        raise ValueError("notification channel_id MUST be non-empty")
    if at.tzinfo is None:
        raise ValueError("notification timestamp MUST be timezone-aware")


async def _fetch_required(
    connection: psycopg.AsyncConnection[dict[str, Any]],
    query: str,
    params: tuple[object, ...],
    message: str,
) -> dict[str, Any]:
    cursor = await connection.execute(query, params)
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError(message)
    return row


async def _timeout(connection: psycopg.AsyncConnection[object], timeout_ms: int) -> None:
    await connection.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")


__all__ = ["PostgresNotificationDeliveryStore"]
