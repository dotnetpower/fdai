"""PostgreSQL append and exact-readback adapter for pre-effect audit intent."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.ontology_query import content_digest
from psycopg.rows import dict_row

from fdai.core.executor.audit_intent import (
    AuditIntentAppendDecision,
    AuditIntentAppendReceipt,
    AuditIntentAppendResult,
    PreEffectAuditIntent,
    audit_intent_to_mapping,
)

_INSERT_SQL = (
    "INSERT INTO executor_audit_intent (intent_key, intent_digest, record) "
    "VALUES (%s, %s, %s::jsonb) ON CONFLICT (intent_key) DO NOTHING "
    "RETURNING recorded_at"
)
_SELECT_SQL = (
    "SELECT intent_digest, record, recorded_at, clock_timestamp() AS read_back_at "
    "FROM executor_audit_intent WHERE intent_key = %s"
)


@dataclass(frozen=True, slots=True)
class PostgresAuditIntentStoreConfig:
    """Connection and statement bounds for the append-only intent store."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresAuditIntentStore:
    """Atomic append, duplicate/conflict classification, and exact readback."""

    production_eligible = True

    def __init__(self, *, config: PostgresAuditIntentStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresAuditIntentStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    async def append_and_readback(
        self,
        intent: PreEffectAuditIntent,
    ) -> AuditIntentAppendResult:
        if type(intent) is not PreEffectAuditIntent:
            raise ValueError("PostgreSQL audit intent store requires an exact intent")
        intent_key = _intent_key(intent)
        mapping = audit_intent_to_mapping(intent)
        encoded = json.dumps(
            mapping,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=False,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                cursor = await connection.execute(
                    _INSERT_SQL,
                    (intent_key, intent.intent_digest, encoded),
                )
                inserted = await cursor.fetchone()
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                readback_cursor = await connection.execute(
                    _SELECT_SQL,
                    (intent_key,),
                )
                row = await readback_cursor.fetchone()
                if row is None:
                    raise ValueError("PostgreSQL audit intent readback is unavailable")
                observed_digest, observed_mapping, persisted_at, read_back_at = _decode_row(row)
                exact_match = bool(
                    observed_digest == intent.intent_digest and observed_mapping == mapping
                )
                if not exact_match:
                    return AuditIntentAppendResult(
                        candidate_intent_digest=intent.intent_digest,
                        decision=AuditIntentAppendDecision.CONFLICT,
                        observed_intent_digest=_observed_digest(
                            observed_digest,
                            observed_mapping,
                            candidate_digest=intent.intent_digest,
                        ),
                        receipt=None,
                    )
                receipt = AuditIntentAppendReceipt.create(
                    intent=intent,
                    persisted_intent_digest=observed_digest,
                    store_receipt_digest=content_digest(
                        {
                            "domain": "postgres-audit-intent-readback",
                            "intent_key": intent_key,
                            "intent_digest": observed_digest,
                            "persisted_at": persisted_at.isoformat(),
                            "read_back_at": read_back_at.isoformat(),
                        }
                    ),
                    persisted_at=persisted_at,
                    read_back_at=read_back_at,
                )
                return AuditIntentAppendResult(
                    candidate_intent_digest=intent.intent_digest,
                    decision=(
                        AuditIntentAppendDecision.APPENDED
                        if inserted is not None
                        else AuditIntentAppendDecision.DUPLICATE_SAME
                    ),
                    observed_intent_digest=observed_digest,
                    receipt=receipt,
                )

    async def _set_statement_timeout(
        self,
        connection: psycopg.AsyncConnection[Any],
    ) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _intent_key(intent: PreEffectAuditIntent) -> str:
    reservation = intent.reservation_receipt.record
    return content_digest(
        {
            "domain": "executor-audit-intent-key",
            "idempotency_key": reservation.identity.idempotency_key,
            "reservation_identity_digest": reservation.identity.identity_digest,
        }
    )


def _decode_row(
    row: Mapping[str, object],
) -> tuple[str, dict[str, object], datetime, datetime]:
    intent_digest = row.get("intent_digest")
    record = row.get("record")
    persisted_at = row.get("recorded_at")
    read_back_at = row.get("read_back_at")
    if type(intent_digest) is not str:
        raise ValueError("PostgreSQL audit intent digest MUST be a string")
    if type(record) is not dict:
        raise ValueError("PostgreSQL audit intent record MUST be a JSON object")
    return (
        intent_digest,
        record,
        _row_datetime(persisted_at, "recorded_at"),
        _row_datetime(read_back_at, "read_back_at"),
    )


def _observed_digest(
    observed_digest: str,
    observed_mapping: Mapping[str, object],
    *,
    candidate_digest: str,
) -> str:
    if (
        observed_digest.startswith("sha256:")
        and len(observed_digest) == 71
        and all(character in "0123456789abcdef" for character in observed_digest[7:])
        and observed_digest != candidate_digest
    ):
        return observed_digest
    return content_digest(
        {
            "domain": "corrupt-postgres-audit-intent",
            "record": observed_mapping,
        }
    )


def _row_datetime(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"PostgreSQL audit intent {name} MUST include a timezone")
    return value.astimezone(UTC)


__all__ = [
    "PostgresAuditIntentStore",
    "PostgresAuditIntentStoreConfig",
]
