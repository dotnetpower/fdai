"""Persist Operator-owned outbound channel delivery and recovery state."""

# ruff: noqa: S608 - interpolated projections are module constants.

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, cast

import psycopg
from fdai_operator_service.families.conversation.channel_delivery_models import (
    MAX_DELIVERY_ATTEMPTS,
    MAX_DELIVERY_LEASE_SECONDS,
    ChannelAdapterBreaker,
    ChannelBreakerMode,
    ChannelDeliveryAcknowledgement,
    ChannelDeliveryAttempt,
    ChannelDeliveryRecord,
    ChannelDeliverySnapshot,
    ChannelDeliveryState,
    ChannelKind,
)
from fdai_operator_service.families.conversation.contracts import JsonObject
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_DELIVERY_COLUMNS: Final = (
    "delivery_id, idempotency_key, principal_id, scope_ref, conversation_id, binding_id, "
    "channel_kind, response, response_digest, state, created_at, due_at, expires_at, "
    "retention_until, attempt_count, lease_owner, lease_expires_at, last_error_code, "
    "duplicate_risk, terminal_at"
)
_ATTEMPT_COLUMNS: Final = (
    "attempt_id, delivery_id, sequence, worker_id, started_at, completed_at, outcome, error_code"
)
_ACK_COLUMNS: Final = (
    "delivery_id, attempt_id, provider_message_id, acknowledged_at, degraded_to_text"
)
_BREAKER_COLUMNS: Final = (
    "adapter_id, channel_kind, mode, failure_timestamps, revision, updated_at, updated_by, reason"
)


@dataclass(frozen=True, slots=True)
class PostgresChannelDeliveryConfig:
    """Configure bounded PostgreSQL connections for outbound delivery."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("channel delivery dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("channel delivery timeouts MUST be positive")


class PostgresChannelDeliveryStore:
    """Persist delivery state with row-lock claims and lease-fenced closure."""

    def __init__(self, *, config: PostgresChannelDeliveryConfig) -> None:
        self._config = config

    async def put(self, record: ChannelDeliveryRecord) -> ChannelDeliveryRecord:
        """Insert one pending response or return its exact idempotent replay."""
        try:
            async with await self._connect() as connection, connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "INSERT INTO conversation_outbound_delivery ("
                    f"{_DELIVERY_COLUMNS}) VALUES ("
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s) "
                    "ON CONFLICT (idempotency_key) DO NOTHING "
                    f"RETURNING {_DELIVERY_COLUMNS}",
                    _delivery_values(record),
                )
                row = await cursor.fetchone()
                if row is not None:
                    return _delivery(row)
                existing_cursor = await connection.execute(
                    f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
                    "WHERE idempotency_key = %s FOR UPDATE",
                    (record.idempotency_key,),
                )
                existing_row = await existing_cursor.fetchone()
                if existing_row is None:
                    raise ValueError("channel delivery disappeared during idempotent insert")
                existing = _delivery(existing_row)
                if _immutable_identity(existing) != _immutable_identity(record):
                    raise ValueError(
                        "channel delivery idempotency key conflicts with different content"
                    )
                return existing
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("channel delivery_id already exists") from exc

    async def get(self, delivery_id: str) -> ChannelDeliveryRecord | None:
        """Read one durable delivery by server-owned id."""
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
                "WHERE delivery_id = %s",
                (delivery_id,),
            )
            row = await cursor.fetchone()
            return _delivery(row) if row is not None else None

    async def claim(
        self,
        *,
        delivery_id: str,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> ChannelDeliveryRecord | None:
        """Claim one eligible delivery and create its attempt atomically."""
        _claim_bounds(lease_seconds=lease_seconds, limit=1)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            current = await self._locked_delivery(connection, delivery_id)
            if current is None:
                return None
            return await self._claim_locked(
                connection,
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
        channel_kind: ChannelKind | None = None,
    ) -> tuple[ChannelDeliveryRecord, ...]:
        """Claim a bounded optional-channel batch with `SKIP LOCKED` isolation."""
        _claim_bounds(lease_seconds=lease_seconds, limit=limit)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
                "WHERE state IN ('pending', 'failed') AND due_at <= %s AND expires_at > %s "
                "AND attempt_count < %s AND (%s::text IS NULL OR channel_kind = %s) "
                "ORDER BY due_at, delivery_id "
                "FOR UPDATE SKIP LOCKED LIMIT %s",
                (
                    now,
                    now,
                    MAX_DELIVERY_ATTEMPTS,
                    channel_kind.value if channel_kind is not None else None,
                    channel_kind.value if channel_kind is not None else None,
                    limit,
                ),
            )
            claimed: list[ChannelDeliveryRecord] = []
            for row in await cursor.fetchall():
                current = _delivery(row)
                result = await self._claim_locked(
                    connection,
                    current,
                    now=now,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                )
                if result is not None:
                    claimed.append(result)
            return tuple(claimed)

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
    ) -> ChannelDeliveryRecord:
        """Close one exact lease and its attempt, acknowledgement, and state atomically."""
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            current = await self._locked_delivery(connection, delivery_id)
            if current is None:
                raise KeyError(delivery_id)
            if current.state.immutable:
                raise ValueError("terminal channel delivery state is immutable")
            if (
                current.state is not ChannelDeliveryState.SENDING
                or current.lease_owner != worker_id
                or current.attempt_count != expected_attempt_count
            ):
                raise ValueError("channel delivery lease compare-and-set failed")
            allowed = {
                ChannelDeliveryState.DELIVERED,
                ChannelDeliveryState.AMBIGUOUS,
                ChannelDeliveryState.FAILED,
                ChannelDeliveryState.ABANDONED,
            }
            if state not in allowed:
                raise ValueError("sending channel delivery has an invalid completion state")
            if state is ChannelDeliveryState.FAILED:
                if next_due_at is None or not current.due_at <= next_due_at < current.expires_at:
                    raise ValueError("failed channel delivery MUST carry a bounded retry time")
            elif next_due_at is not None:
                raise ValueError("only failed channel delivery can carry next_due_at")
            expected_attempt_id = _attempt_id(delivery_id, expected_attempt_count)
            if acknowledgement is not None and (
                state is not ChannelDeliveryState.DELIVERED
                or acknowledgement.delivery_id != delivery_id
                or acknowledgement.attempt_id != expected_attempt_id
            ):
                raise ValueError("channel delivery acknowledgement does not match completion")
            terminal_at = at if state.immutable else None
            cursor = await connection.execute(
                "UPDATE conversation_outbound_delivery SET "
                "state = %s, due_at = %s, lease_owner = NULL, lease_expires_at = NULL, "
                "last_error_code = %s, duplicate_risk = %s, terminal_at = %s "
                "WHERE delivery_id = %s AND state = 'sending' AND lease_owner = %s "
                "AND attempt_count = %s "
                f"RETURNING {_DELIVERY_COLUMNS}",
                (
                    state.value,
                    next_due_at or current.due_at,
                    error_code,
                    state is ChannelDeliveryState.AMBIGUOUS,
                    terminal_at,
                    delivery_id,
                    worker_id,
                    expected_attempt_count,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("channel delivery lease compare-and-set failed")
            attempt_cursor = await connection.execute(
                "UPDATE conversation_outbound_delivery_attempt "
                "SET completed_at = %s, outcome = %s, error_code = %s "
                "WHERE attempt_id = %s AND completed_at IS NULL",
                (at, state.value, error_code, expected_attempt_id),
            )
            if attempt_cursor.rowcount != 1:
                raise ValueError("channel delivery attempt completion compare-and-set failed")
            if acknowledgement is not None:
                await connection.execute(
                    "INSERT INTO conversation_outbound_delivery_acknowledgement ("
                    f"{_ACK_COLUMNS}) VALUES (%s, %s, %s, %s, %s)",
                    (
                        acknowledgement.delivery_id,
                        acknowledgement.attempt_id,
                        acknowledgement.provider_message_id,
                        acknowledgement.acknowledged_at,
                        acknowledgement.degraded_to_text,
                    ),
                )
            return _delivery(row)

    async def reconcile_sending(self, *, now: datetime) -> int:
        """Close expired sending leases as immutable ambiguous duplicate risk."""
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
                "WHERE state = 'sending' AND lease_expires_at <= %s "
                "ORDER BY lease_expires_at, delivery_id FOR UPDATE SKIP LOCKED",
                (now,),
            )
            records = [_delivery(row) for row in await cursor.fetchall()]
            for current in records:
                await connection.execute(
                    "UPDATE conversation_outbound_delivery SET "
                    "state = 'ambiguous', lease_owner = NULL, lease_expires_at = NULL, "
                    "last_error_code = 'process_loss', duplicate_risk = TRUE, terminal_at = %s "
                    "WHERE delivery_id = %s AND state = 'sending'",
                    (now, current.delivery_id),
                )
                await connection.execute(
                    "UPDATE conversation_outbound_delivery_attempt SET "
                    "completed_at = %s, outcome = 'ambiguous', error_code = 'process_loss' "
                    "WHERE attempt_id = %s AND completed_at IS NULL",
                    (now, _attempt_id(current.delivery_id, current.attempt_count)),
                )
            return len(records)

    async def snapshot(self, *, limit: int = 200) -> ChannelDeliverySnapshot:
        """Read a bounded operational snapshot without response regeneration."""
        if not 1 <= limit <= 500:
            raise ValueError("channel delivery snapshot limit is invalid")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            deliveries = await connection.execute(
                f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
                "ORDER BY created_at DESC, delivery_id LIMIT %s",
                (limit,),
            )
            attempts = await connection.execute(
                f"SELECT {_ATTEMPT_COLUMNS} FROM conversation_outbound_delivery_attempt "
                "ORDER BY started_at DESC, attempt_id LIMIT %s",
                (limit,),
            )
            acknowledgements = await connection.execute(
                f"SELECT {_ACK_COLUMNS} FROM conversation_outbound_delivery_acknowledgement "
                "ORDER BY acknowledged_at DESC, delivery_id LIMIT %s",
                (limit,),
            )
            breakers = await connection.execute(
                f"SELECT {_BREAKER_COLUMNS} FROM conversation_adapter_breaker "
                "ORDER BY updated_at DESC, adapter_id LIMIT %s",
                (limit,),
            )
            return ChannelDeliverySnapshot(
                deliveries=tuple(_delivery(row) for row in await deliveries.fetchall()),
                attempts=tuple(_attempt(row) for row in await attempts.fetchall()),
                acknowledgements=tuple(
                    _acknowledgement(row) for row in await acknowledgements.fetchall()
                ),
                breakers=tuple(_breaker(row) for row in await breakers.fetchall()),
            )

    async def delete_expired(self, *, now: datetime, limit: int = 200) -> int:
        """Delete only retention-expired terminal rows in one bounded batch."""
        if not 1 <= limit <= 500:
            raise ValueError("channel delivery retention limit is invalid")
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "WITH expired AS ("
                "SELECT delivery_id FROM conversation_outbound_delivery "
                "WHERE state IN ('delivered', 'ambiguous', 'abandoned') "
                "AND retention_until <= %s ORDER BY retention_until, delivery_id "
                "FOR UPDATE SKIP LOCKED LIMIT %s) "
                "DELETE FROM conversation_outbound_delivery target USING expired "
                "WHERE target.delivery_id = expired.delivery_id RETURNING target.delivery_id",
                (now, limit),
            )
            return len(await cursor.fetchall())

    async def get_breaker(self, adapter_id: str) -> ChannelAdapterBreaker | None:
        """Read one provider-adapter breaker by stable adapter id."""
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_BREAKER_COLUMNS} FROM conversation_adapter_breaker "
                "WHERE adapter_id = %s",
                (adapter_id,),
            )
            row = await cursor.fetchone()
            return _breaker(row) if row is not None else None

    async def put_breaker(
        self,
        record: ChannelAdapterBreaker,
        *,
        expected_revision: int | None,
    ) -> ChannelAdapterBreaker:
        """Create or compare-and-set one breaker revision."""
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            if expected_revision is None:
                cursor = await connection.execute(
                    "INSERT INTO conversation_adapter_breaker ("
                    f"{_BREAKER_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (adapter_id) DO NOTHING "
                    f"RETURNING {_BREAKER_COLUMNS}",
                    _breaker_values(record),
                )
            else:
                cursor = await connection.execute(
                    "UPDATE conversation_adapter_breaker SET "
                    "channel_kind = %s, mode = %s, failure_timestamps = %s, revision = %s, "
                    "updated_at = %s, updated_by = %s, reason = %s "
                    "WHERE adapter_id = %s AND revision = %s "
                    f"RETURNING {_BREAKER_COLUMNS}",
                    (
                        record.channel_kind.value,
                        record.mode.value,
                        Jsonb([value.isoformat() for value in record.failure_timestamps]),
                        record.revision,
                        record.updated_at,
                        record.updated_by,
                        record.reason,
                        record.adapter_id,
                        expected_revision,
                    ),
                )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("channel adapter breaker compare-and-set failed")
            return _breaker(row)

    async def _locked_delivery(
        self,
        connection: psycopg.AsyncConnection[Any],
        delivery_id: str,
    ) -> ChannelDeliveryRecord | None:
        cursor = await connection.execute(
            f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
            "WHERE delivery_id = %s FOR UPDATE",
            (delivery_id,),
        )
        row = await cursor.fetchone()
        return _delivery(row) if row is not None else None

    async def _claim_locked(
        self,
        connection: psycopg.AsyncConnection[Any],
        current: ChannelDeliveryRecord,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> ChannelDeliveryRecord | None:
        if current.state not in {ChannelDeliveryState.PENDING, ChannelDeliveryState.FAILED}:
            return None
        if current.due_at > now or current.expires_at <= now:
            return None
        attempt_count = current.attempt_count + 1
        if attempt_count > MAX_DELIVERY_ATTEMPTS:
            return None
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        cursor = await connection.execute(
            "UPDATE conversation_outbound_delivery SET "
            "state = 'sending', attempt_count = %s, lease_owner = %s, lease_expires_at = %s, "
            "last_error_code = NULL WHERE delivery_id = %s "
            f"RETURNING {_DELIVERY_COLUMNS}",
            (attempt_count, worker_id, lease_expires_at, current.delivery_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("channel delivery claim disappeared")
        await connection.execute(
            "INSERT INTO conversation_outbound_delivery_attempt ("
            f"{_ATTEMPT_COLUMNS}) VALUES (%s, %s, %s, %s, %s, NULL, NULL, NULL)",
            (
                _attempt_id(current.delivery_id, attempt_count),
                current.delivery_id,
                attempt_count,
                worker_id,
                now,
            ),
        )
        return _delivery(row)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            _psycopg_dsn(self._config.dsn),
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _delivery_values(record: ChannelDeliveryRecord) -> tuple[object, ...]:
    return (
        record.delivery_id,
        record.idempotency_key,
        record.principal_id,
        record.scope_ref,
        record.conversation_id,
        record.binding_id,
        record.channel_kind.value,
        Jsonb(record.response),
        record.response_digest,
        record.state.value,
        record.created_at,
        record.due_at,
        record.expires_at,
        record.retention_until,
        record.attempt_count,
        record.lease_owner,
        record.lease_expires_at,
        record.last_error_code,
        record.duplicate_risk,
        record.terminal_at,
    )


def _immutable_identity(record: ChannelDeliveryRecord) -> tuple[object, ...]:
    return (
        record.principal_id,
        record.scope_ref,
        record.conversation_id,
        record.binding_id,
        record.channel_kind,
        record.response_digest,
        record.created_at,
        record.expires_at,
        record.retention_until,
    )


def _delivery(row: dict[str, Any]) -> ChannelDeliveryRecord:
    return ChannelDeliveryRecord(
        delivery_id=str(row["delivery_id"]),
        idempotency_key=str(row["idempotency_key"]),
        principal_id=str(row["principal_id"]),
        scope_ref=str(row["scope_ref"]),
        conversation_id=str(row["conversation_id"]),
        binding_id=str(row["binding_id"]) if row["binding_id"] is not None else None,
        channel_kind=ChannelKind(str(row["channel_kind"])),
        response=_json_object(row["response"]),
        response_digest=str(row["response_digest"]),
        state=ChannelDeliveryState(str(row["state"])),
        created_at=row["created_at"],
        due_at=row["due_at"],
        expires_at=row["expires_at"],
        retention_until=row["retention_until"],
        attempt_count=int(row["attempt_count"]),
        lease_owner=str(row["lease_owner"]) if row["lease_owner"] is not None else None,
        lease_expires_at=row["lease_expires_at"],
        last_error_code=(
            str(row["last_error_code"]) if row["last_error_code"] is not None else None
        ),
        duplicate_risk=bool(row["duplicate_risk"]),
        terminal_at=row["terminal_at"],
    )


def _attempt(row: dict[str, Any]) -> ChannelDeliveryAttempt:
    return ChannelDeliveryAttempt(
        attempt_id=str(row["attempt_id"]),
        delivery_id=str(row["delivery_id"]),
        sequence=int(row["sequence"]),
        worker_id=str(row["worker_id"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        outcome=(ChannelDeliveryState(str(row["outcome"])) if row["outcome"] is not None else None),
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
    )


def _acknowledgement(row: dict[str, Any]) -> ChannelDeliveryAcknowledgement:
    return ChannelDeliveryAcknowledgement(
        delivery_id=str(row["delivery_id"]),
        attempt_id=str(row["attempt_id"]),
        provider_message_id=str(row["provider_message_id"]),
        acknowledged_at=row["acknowledged_at"],
        degraded_to_text=bool(row["degraded_to_text"]),
    )


def _breaker(row: dict[str, Any]) -> ChannelAdapterBreaker:
    raw_timestamps = row["failure_timestamps"]
    if not isinstance(raw_timestamps, list):
        raise ValueError("stored channel adapter breaker timestamps MUST be an array")
    return ChannelAdapterBreaker(
        adapter_id=str(row["adapter_id"]),
        channel_kind=ChannelKind(str(row["channel_kind"])),
        mode=ChannelBreakerMode(str(row["mode"])),
        failure_timestamps=tuple(datetime.fromisoformat(str(value)) for value in raw_timestamps),
        revision=int(row["revision"]),
        updated_at=row["updated_at"],
        updated_by=str(row["updated_by"]),
        reason=str(row["reason"]),
    )


def _breaker_values(record: ChannelAdapterBreaker) -> tuple[object, ...]:
    return (
        record.adapter_id,
        record.channel_kind.value,
        record.mode.value,
        Jsonb([value.isoformat() for value in record.failure_timestamps]),
        record.revision,
        record.updated_at,
        record.updated_by,
        record.reason,
    )


def _json_object(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        raise ValueError("stored channel delivery response MUST be an object")
    return cast(JsonObject, dict(value))


def _claim_bounds(*, lease_seconds: int, limit: int) -> None:
    if not 1 <= lease_seconds <= MAX_DELIVERY_LEASE_SECONDS or not 1 <= limit <= 200:
        raise ValueError("channel delivery claim bounds are invalid")


def _attempt_id(delivery_id: str, sequence: int) -> str:
    return f"{delivery_id}:attempt:{sequence}"


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


__all__ = ["PostgresChannelDeliveryConfig", "PostgresChannelDeliveryStore"]
