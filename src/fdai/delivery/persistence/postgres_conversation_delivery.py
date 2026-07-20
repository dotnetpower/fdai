"""PostgreSQL persistence for durable outbound conversation delivery."""

# ruff: noqa: S608 - SQL identifiers are module constants; runtime values are parametrized.

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    outbound_response_from_json,
    outbound_response_to_json,
)
from fdai.shared.providers.conversation_delivery import (
    MAX_DELIVERY_ATTEMPTS,
    MAX_DELIVERY_LEASE_SECONDS,
    AdapterBreakerMode,
    AdapterBreakerRecord,
    ConversationDeliverySnapshot,
    ConversationDeliveryStore,
    OutboundDeliveryAcknowledgement,
    OutboundDeliveryAttempt,
    OutboundDeliveryRecord,
    OutboundDeliveryState,
)

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
class PostgresConversationDeliveryStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("delivery store dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("delivery store timeouts MUST be positive")


class PostgresConversationDeliveryStore(ConversationDeliveryStore):
    """Transactional delivery ledger with row-level compare-and-set claims."""

    def __init__(self, *, config: PostgresConversationDeliveryStoreConfig) -> None:
        self._config = config

    async def put(self, record: OutboundDeliveryRecord) -> OutboundDeliveryRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO conversation_outbound_delivery ({_DELIVERY_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (idempotency_key) DO NOTHING RETURNING delivery_id",
                _delivery_values(record),
            )
            if await cursor.fetchone() is not None:
                return record
            current = await self._select_by_idempotency(connection, record.idempotency_key)
            if current is None or current.response_digest != record.response_digest:
                raise ValueError("delivery idempotency key was reused with different response")
            return current

    async def get(self, delivery_id: str) -> OutboundDeliveryRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await self._select(connection, delivery_id)

    async def claim(
        self,
        *,
        delivery_id: str,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> OutboundDeliveryRecord | None:
        _claim_bounds(lease_seconds=lease_seconds, limit=1)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
                "WHERE delivery_id = %s FOR UPDATE",
                (delivery_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return await self._claim_locked(
                connection,
                _row_to_delivery(row),
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
        _claim_bounds(lease_seconds=lease_seconds, limit=limit)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
                "WHERE state IN ('pending', 'failed') AND due_at <= %s AND expires_at > %s "
                "ORDER BY due_at, delivery_id FOR UPDATE SKIP LOCKED LIMIT %s",
                (now, now, limit),
            )
            claimed: list[OutboundDeliveryRecord] = []
            for row in await cursor.fetchall():
                record = await self._claim_locked(
                    connection,
                    _row_to_delivery(row),
                    now=now,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                )
                if record is not None:
                    claimed.append(record)
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
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            current = await self._select_for_update(connection, delivery_id)
            if current is None:
                raise KeyError(delivery_id)
            updated = _finished_record(
                current,
                worker_id=worker_id,
                expected_attempt_count=expected_attempt_count,
                state=state,
                at=at,
                next_due_at=next_due_at,
                error_code=error_code,
                acknowledgement=acknowledgement,
            )
            cursor = await connection.execute(
                "UPDATE conversation_outbound_delivery SET state = %s, due_at = %s, "
                "lease_owner = NULL, lease_expires_at = NULL, last_error_code = %s, "
                "duplicate_risk = %s, terminal_at = %s "
                "WHERE delivery_id = %s AND state = 'sending' AND lease_owner = %s "
                "AND attempt_count = %s RETURNING delivery_id",
                (
                    updated.state.value,
                    updated.due_at,
                    updated.last_error_code,
                    updated.duplicate_risk,
                    updated.terminal_at,
                    delivery_id,
                    worker_id,
                    expected_attempt_count,
                ),
            )
            if await cursor.fetchone() is None:
                raise ValueError("delivery lease compare-and-set failed")
            attempt_id = _attempt_id(delivery_id, expected_attempt_count)
            await connection.execute(
                "UPDATE conversation_outbound_delivery_attempt "
                "SET completed_at = %s, outcome = %s, error_code = %s "
                "WHERE attempt_id = %s",
                (at, state.value, error_code, attempt_id),
            )
            if acknowledgement is not None:
                await connection.execute(
                    f"INSERT INTO conversation_outbound_delivery_acknowledgement ({_ACK_COLUMNS}) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    _ack_values(acknowledgement),
                )
            return updated

    async def reconcile_sending(self, *, now: datetime) -> int:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE conversation_outbound_delivery "
                "SET state = 'ambiguous', lease_owner = NULL, lease_expires_at = NULL, "
                "last_error_code = 'process_loss', duplicate_risk = TRUE, terminal_at = %s "
                "WHERE state = 'sending' AND lease_expires_at <= %s "
                "RETURNING delivery_id, attempt_count",
                (now, now),
            )
            rows = await cursor.fetchall()
            for row in rows:
                await connection.execute(
                    "UPDATE conversation_outbound_delivery_attempt "
                    "SET completed_at = %s, outcome = 'ambiguous', error_code = 'process_loss' "
                    "WHERE delivery_id = %s AND sequence = %s AND completed_at IS NULL",
                    (now, row["delivery_id"], row["attempt_count"]),
                )
            return len(rows)

    async def snapshot(self, *, limit: int = 200) -> ConversationDeliverySnapshot:
        if not 1 <= limit <= 500:
            raise ValueError("delivery snapshot limit is invalid")
        async with await self._connect() as connection:
            await self._timeout(connection)
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
            return ConversationDeliverySnapshot(
                deliveries=tuple(_row_to_delivery(row) for row in await deliveries.fetchall()),
                attempts=tuple(_row_to_attempt(row) for row in await attempts.fetchall()),
                acknowledgements=tuple(
                    _row_to_ack(row) for row in await acknowledgements.fetchall()
                ),
                breakers=tuple(_row_to_breaker(row) for row in await breakers.fetchall()),
            )

    async def get_breaker(self, adapter_id: str) -> AdapterBreakerRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_BREAKER_COLUMNS} FROM conversation_adapter_breaker "
                "WHERE adapter_id = %s",
                (adapter_id,),
            )
            row = await cursor.fetchone()
        return _row_to_breaker(row) if row is not None else None

    async def put_breaker(
        self,
        record: AdapterBreakerRecord,
        *,
        expected_revision: int | None,
    ) -> AdapterBreakerRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            if expected_revision is None:
                cursor = await connection.execute(
                    f"INSERT INTO conversation_adapter_breaker ({_BREAKER_COLUMNS}) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s) "
                    "ON CONFLICT (adapter_id) DO NOTHING RETURNING adapter_id",
                    _breaker_values(record),
                )
            else:
                cursor = await connection.execute(
                    "UPDATE conversation_adapter_breaker SET channel_kind = %s, mode = %s, "
                    "failure_timestamps = %s::jsonb, revision = %s, updated_at = %s, "
                    "updated_by = %s, reason = %s WHERE adapter_id = %s AND revision = %s "
                    "RETURNING adapter_id",
                    (
                        record.channel_kind.value,
                        record.mode.value,
                        _failure_json(record),
                        record.revision,
                        record.updated_at,
                        record.updated_by,
                        record.reason,
                        record.adapter_id,
                        expected_revision,
                    ),
                )
            if await cursor.fetchone() is None:
                raise ValueError("adapter breaker compare-and-set failed")
            return record

    async def purge_retained(self, *, now: datetime, limit: int = 500) -> int:
        """Delete only terminal rows whose retention window has elapsed."""
        if not 1 <= limit <= 5000:
            raise ValueError("delivery retention purge limit is invalid")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH expired AS ("
                "SELECT delivery_id FROM conversation_outbound_delivery "
                "WHERE state IN ('delivered', 'ambiguous', 'abandoned') "
                "AND retention_until <= %s ORDER BY retention_until, delivery_id LIMIT %s"
                ") DELETE FROM conversation_outbound_delivery delivery USING expired "
                "WHERE delivery.delivery_id = expired.delivery_id RETURNING delivery.delivery_id",
                (now, limit),
            )
            return len(await cursor.fetchall())

    async def _claim_locked(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        current: OutboundDeliveryRecord,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> OutboundDeliveryRecord | None:
        if (
            current.state not in {OutboundDeliveryState.PENDING, OutboundDeliveryState.FAILED}
            or current.due_at > now
            or current.expires_at <= now
            or current.attempt_count >= MAX_DELIVERY_ATTEMPTS
        ):
            return None
        claimed = replace(
            current,
            state=OutboundDeliveryState.SENDING,
            attempt_count=current.attempt_count + 1,
            lease_owner=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            last_error_code=None,
        )
        cursor = await connection.execute(
            "UPDATE conversation_outbound_delivery SET state = 'sending', attempt_count = %s, "
            "lease_owner = %s, lease_expires_at = %s, last_error_code = NULL "
            "WHERE delivery_id = %s AND state = %s AND attempt_count = %s RETURNING delivery_id",
            (
                claimed.attempt_count,
                worker_id,
                claimed.lease_expires_at,
                current.delivery_id,
                current.state.value,
                current.attempt_count,
            ),
        )
        if await cursor.fetchone() is None:
            return None
        attempt = OutboundDeliveryAttempt(
            attempt_id=_attempt_id(current.delivery_id, claimed.attempt_count),
            delivery_id=current.delivery_id,
            sequence=claimed.attempt_count,
            worker_id=worker_id,
            started_at=now,
        )
        await connection.execute(
            f"INSERT INTO conversation_outbound_delivery_attempt ({_ATTEMPT_COLUMNS}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            _attempt_values(attempt),
        )
        return claimed

    async def _select(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        delivery_id: str,
    ) -> OutboundDeliveryRecord | None:
        cursor = await connection.execute(
            f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
            "WHERE delivery_id = %s",
            (delivery_id,),
        )
        row = await cursor.fetchone()
        return _row_to_delivery(row) if row is not None else None

    async def _select_for_update(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        delivery_id: str,
    ) -> OutboundDeliveryRecord | None:
        cursor = await connection.execute(
            f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
            "WHERE delivery_id = %s FOR UPDATE",
            (delivery_id,),
        )
        row = await cursor.fetchone()
        return _row_to_delivery(row) if row is not None else None

    async def _select_by_idempotency(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        idempotency_key: str,
    ) -> OutboundDeliveryRecord | None:
        cursor = await connection.execute(
            f"SELECT {_DELIVERY_COLUMNS} FROM conversation_outbound_delivery "
            "WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        row = await cursor.fetchone()
        return _row_to_delivery(row) if row is not None else None

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _finished_record(
    current: OutboundDeliveryRecord,
    *,
    worker_id: str,
    expected_attempt_count: int,
    state: OutboundDeliveryState,
    at: datetime,
    next_due_at: datetime | None,
    error_code: str | None,
    acknowledgement: OutboundDeliveryAcknowledgement | None,
) -> OutboundDeliveryRecord:
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
    if acknowledgement is not None and state is not OutboundDeliveryState.DELIVERED:
        raise ValueError("only delivered state can persist acknowledgement")
    return replace(
        current,
        state=state,
        due_at=next_due_at or current.due_at,
        lease_owner=None,
        lease_expires_at=None,
        last_error_code=error_code,
        duplicate_risk=state is OutboundDeliveryState.AMBIGUOUS,
        terminal_at=at if state.immutable else None,
    )


def _claim_bounds(*, lease_seconds: int, limit: int) -> None:
    if not 1 <= lease_seconds <= MAX_DELIVERY_LEASE_SECONDS or not 1 <= limit <= 200:
        raise ValueError("delivery claim bounds are invalid")


def _delivery_values(record: OutboundDeliveryRecord) -> tuple[object, ...]:
    return (
        record.delivery_id,
        record.idempotency_key,
        record.principal_id,
        record.scope_ref,
        record.conversation_id,
        record.binding_id,
        record.response.channel_kind.value,
        json.dumps(outbound_response_to_json(record.response), sort_keys=True),
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


def _row_to_delivery(row: dict[str, Any]) -> OutboundDeliveryRecord:
    response = json.loads(row["response"]) if isinstance(row["response"], str) else row["response"]
    return OutboundDeliveryRecord(
        delivery_id=str(row["delivery_id"]),
        idempotency_key=str(row["idempotency_key"]),
        principal_id=str(row["principal_id"]),
        scope_ref=str(row["scope_ref"]),
        conversation_id=str(row["conversation_id"]),
        binding_id=str(row["binding_id"]) if row["binding_id"] is not None else None,
        response=outbound_response_from_json(response),
        response_digest=str(row["response_digest"]),
        state=OutboundDeliveryState(str(row["state"])),
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


def _attempt_values(attempt: OutboundDeliveryAttempt) -> tuple[object, ...]:
    return (
        attempt.attempt_id,
        attempt.delivery_id,
        attempt.sequence,
        attempt.worker_id,
        attempt.started_at,
        attempt.completed_at,
        attempt.outcome.value if attempt.outcome is not None else None,
        attempt.error_code,
    )


def _row_to_attempt(row: dict[str, Any]) -> OutboundDeliveryAttempt:
    return OutboundDeliveryAttempt(
        attempt_id=str(row["attempt_id"]),
        delivery_id=str(row["delivery_id"]),
        sequence=int(row["sequence"]),
        worker_id=str(row["worker_id"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        outcome=(
            OutboundDeliveryState(str(row["outcome"])) if row["outcome"] is not None else None
        ),
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
    )


def _ack_values(ack: OutboundDeliveryAcknowledgement) -> tuple[object, ...]:
    return (
        ack.delivery_id,
        ack.attempt_id,
        ack.provider_message_id,
        ack.acknowledged_at,
        ack.degraded_to_text,
    )


def _row_to_ack(row: dict[str, Any]) -> OutboundDeliveryAcknowledgement:
    return OutboundDeliveryAcknowledgement(
        delivery_id=str(row["delivery_id"]),
        attempt_id=str(row["attempt_id"]),
        provider_message_id=str(row["provider_message_id"]),
        acknowledged_at=row["acknowledged_at"],
        degraded_to_text=bool(row["degraded_to_text"]),
    )


def _failure_json(record: AdapterBreakerRecord) -> str:
    return json.dumps([value.isoformat() for value in record.failure_timestamps])


def _breaker_values(record: AdapterBreakerRecord) -> tuple[object, ...]:
    return (
        record.adapter_id,
        record.channel_kind.value,
        record.mode.value,
        _failure_json(record),
        record.revision,
        record.updated_at,
        record.updated_by,
        record.reason,
    )


def _row_to_breaker(row: dict[str, Any]) -> AdapterBreakerRecord:
    failures = (
        json.loads(row["failure_timestamps"])
        if isinstance(row["failure_timestamps"], str)
        else row["failure_timestamps"]
    )
    return AdapterBreakerRecord(
        adapter_id=str(row["adapter_id"]),
        channel_kind=ConversationChannelKind(str(row["channel_kind"])),
        mode=AdapterBreakerMode(str(row["mode"])),
        failure_timestamps=tuple(datetime.fromisoformat(str(value)) for value in failures),
        revision=int(row["revision"]),
        updated_at=row["updated_at"],
        updated_by=str(row["updated_by"]),
        reason=str(row["reason"]),
    )


def _attempt_id(delivery_id: str, sequence: int) -> str:
    return f"{delivery_id}:attempt:{sequence}"


__all__ = [
    "PostgresConversationDeliveryStore",
    "PostgresConversationDeliveryStoreConfig",
]
