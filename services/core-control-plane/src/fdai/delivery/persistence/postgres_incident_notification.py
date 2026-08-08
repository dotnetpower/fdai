"""PostgreSQL atomic delivery claims for incident notifications."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from fdai.core.incident.notification_delivery import (
    NotificationClaimStatus,
    NotificationDeliveryClaim,
)
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig

_KEY_PREFIX = "incident-notification:"


class PostgresIncidentNotificationDeliveryStore:
    """Use one locked ``state_kv`` row per stable notification audit id."""

    def __init__(self, *, config: PostgresStateStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresStateStoreConfig.dsn MUST NOT be empty")
        self._config = config

    async def claim(
        self,
        *,
        audit_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> NotificationDeliveryClaim:
        _validate(audit_id, now, lease_seconds)
        key = _key(audit_id)
        token = str(uuid4())
        candidate = _sending_record(token, now, lease_seconds)
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await _timeout(connection, self._config.statement_timeout_ms)
                inserted = await connection.execute(
                    """
                    INSERT INTO state_kv (key, value)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (key) DO NOTHING
                    RETURNING key
                    """,
                    (key, json.dumps(candidate)),
                )
                if await inserted.fetchone() is not None:
                    return NotificationDeliveryClaim(NotificationClaimStatus.CLAIMED, token)
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                    (key,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("incident notification claim row disappeared")
                record = _record(row["value"])
                if record.get("status") == "sent":
                    return NotificationDeliveryClaim(NotificationClaimStatus.SENT)
                lease_until = _parse_time(record.get("lease_until"), "lease_until")
                if record.get("status") == "sending" and lease_until > now:
                    return NotificationDeliveryClaim(NotificationClaimStatus.IN_PROGRESS)
                await connection.execute(
                    "UPDATE state_kv SET value = %s::jsonb, updated_at = NOW() WHERE key = %s",
                    (json.dumps(candidate), key),
                )
                return NotificationDeliveryClaim(NotificationClaimStatus.CLAIMED, token)

    async def complete(self, *, audit_id: str, token: str, at: datetime) -> None:
        if not token:
            raise ValueError("incident notification claim token MUST be non-empty")
        if at.tzinfo is None:
            raise ValueError("incident notification completion time MUST be timezone-aware")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await _timeout(connection, self._config.statement_timeout_ms)
                cursor = await connection.execute(
                    """
                    UPDATE state_kv
                    SET value = %s::jsonb, updated_at = NOW()
                    WHERE key = %s
                      AND value->>'status' = 'sending'
                      AND value->>'token' = %s
                    """,
                    (
                        json.dumps({"status": "sent", "sent_at": at.isoformat()}),
                        _key(audit_id),
                        token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("incident notification claim token mismatch")

    async def release(self, *, audit_id: str, token: str) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await _timeout(connection, self._config.statement_timeout_ms)
                await connection.execute(
                    """
                    DELETE FROM state_kv
                    WHERE key = %s
                      AND value->>'status' = 'sending'
                      AND value->>'token' = %s
                    """,
                    (_key(audit_id), token),
                )


def _key(audit_id: str) -> str:
    return f"{_KEY_PREFIX}{hashlib.sha256(audit_id.encode()).hexdigest()}"


def _sending_record(token: str, now: datetime, lease_seconds: int) -> dict[str, str]:
    return {
        "status": "sending",
        "token": token,
        "lease_until": (now + timedelta(seconds=lease_seconds)).isoformat(),
    }


def _record(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    raise RuntimeError("incident notification state value is not a JSON object")


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError(f"incident notification {field} is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise RuntimeError(f"incident notification {field} is timezone-naive")
    return parsed


def _validate(audit_id: str, now: datetime, lease_seconds: int) -> None:
    if not audit_id:
        raise ValueError("incident notification audit_id MUST be non-empty")
    if now.tzinfo is None:
        raise ValueError("incident notification claim time MUST be timezone-aware")
    if lease_seconds < 1:
        raise ValueError("incident notification lease_seconds MUST be >= 1")


async def _timeout(connection: psycopg.AsyncConnection[object], timeout_ms: int) -> None:
    await connection.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")


__all__ = ["PostgresIncidentNotificationDeliveryStore"]
