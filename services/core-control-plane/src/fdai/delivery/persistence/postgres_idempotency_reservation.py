"""PostgreSQL adapter for crash-safe executor idempotency reservations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.ontology_query import content_digest
from psycopg.rows import dict_row

from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationRecord,
    IdempotencyReservationReserveResult,
    IdempotencyReservationTransitionReceipt,
    ReservationMatch,
    ReservationState,
    classify_reservation,
    reservation_record_from_mapping,
    reservation_record_to_mapping,
)

_KEY_PREFIX = "executor-reservation:"
_SELECT_SQL = (
    "SELECT result, recorded_at FROM executor_idempotency_reservation WHERE idempotency_key = %s"
)
_SELECT_FOR_UPDATE_SQL = _SELECT_SQL + " FOR UPDATE"
_INSERT_SQL = (
    "INSERT INTO executor_idempotency_reservation (idempotency_key, result) "
    "VALUES (%s, %s::jsonb) ON CONFLICT (idempotency_key) DO NOTHING "
    "RETURNING recorded_at"
)
_UPDATE_SQL = (
    "UPDATE executor_idempotency_reservation "
    "SET result = %s::jsonb, recorded_at = clock_timestamp() "
    "WHERE idempotency_key = %s AND result = %s::jsonb "
    "RETURNING recorded_at"
)


class ReservationCompareAndSetError(RuntimeError):
    """The authoritative reservation no longer matches the expected record."""


@dataclass(frozen=True, slots=True)
class PostgresIdempotencyReservationStoreConfig:
    """Connection and statement bounds for the reservation adapter."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresIdempotencyReservationStore:
    """Atomic reserve, exact predecessor CAS, and authoritative readback."""

    production_eligible = True

    def __init__(
        self,
        *,
        config: PostgresIdempotencyReservationStoreConfig,
    ) -> None:
        if not config.dsn:
            raise ValueError("PostgresIdempotencyReservationStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    async def reserve(
        self,
        record: IdempotencyReservationRecord,
    ) -> IdempotencyReservationReserveResult:
        if (
            type(record) is not IdempotencyReservationRecord
            or record.state is not ReservationState.RESERVED
            or record.revision != 1
        ):
            raise ValueError("PostgreSQL reservation insert requires revision-one reserved state")
        key = reservation_storage_key(record.identity.idempotency_key)
        encoded = json.dumps(
            reservation_record_to_mapping(record),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._prepare(connection)
                cursor = await connection.execute(_INSERT_SQL, (key, encoded))
                inserted = await cursor.fetchone()
                observed, recorded_at = await self._read_on_connection(
                    connection,
                    key,
                    for_update=True,
                )
                if inserted is None:
                    return IdempotencyReservationReserveResult(
                        candidate_identity=record.identity,
                        match=classify_reservation(observed, record.identity),
                        observed_record=observed,
                        transition_receipt=None,
                    )
                if observed != record:
                    raise ValueError("PostgreSQL reservation insert readback mismatched candidate")
                transition = _transition_receipt(
                    prior=None,
                    record=observed,
                    expected_prior_revision=0,
                    recorded_at=recorded_at,
                )
                return IdempotencyReservationReserveResult(
                    candidate_identity=record.identity,
                    match=ReservationMatch.ACQUIRED,
                    observed_record=observed,
                    transition_receipt=transition,
                )

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_prior_revision: int,
        record: IdempotencyReservationRecord,
    ) -> IdempotencyReservationTransitionReceipt:
        key = reservation_storage_key(record.identity.idempotency_key)
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._prepare(connection)
                prior, _prior_recorded_at = await self._read_on_connection(
                    connection,
                    key,
                    for_update=True,
                )
                if (
                    prior.record_digest != prior_record_digest
                    or prior.revision != expected_prior_revision
                ):
                    raise ReservationCompareAndSetError(
                        "PostgreSQL reservation predecessor changed"
                    )
                encoded_prior = json.dumps(
                    reservation_record_to_mapping(prior),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                encoded_record = json.dumps(
                    reservation_record_to_mapping(record),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                cursor = await connection.execute(
                    _UPDATE_SQL,
                    (encoded_record, key, encoded_prior),
                )
                updated = await cursor.fetchone()
                if updated is None:
                    raise ReservationCompareAndSetError(
                        "PostgreSQL reservation compare-and-set lost"
                    )
                observed, recorded_at = await self._read_on_connection(
                    connection,
                    key,
                    for_update=True,
                )
                if observed != record:
                    raise ValueError("PostgreSQL reservation update readback mismatched candidate")
                return _transition_receipt(
                    prior=prior,
                    record=observed,
                    expected_prior_revision=expected_prior_revision,
                    recorded_at=recorded_at,
                )

    async def read(
        self,
        idempotency_key: str,
    ) -> IdempotencyReservationRecord | None:
        key = reservation_storage_key(idempotency_key)
        async with await self._connect() as connection:
            await self._prepare(connection)
            cursor = await connection.execute(_SELECT_SQL, (key,))
            row = await cursor.fetchone()
            if row is None:
                return None
            record, _recorded_at = _decode_row(row)
            return record

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=False,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _prepare(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )

    async def _read_on_connection(
        self,
        connection: psycopg.AsyncConnection[Any],
        key: str,
        *,
        for_update: bool,
    ) -> tuple[IdempotencyReservationRecord, datetime]:
        cursor = await connection.execute(
            _SELECT_FOR_UPDATE_SQL if for_update else _SELECT_SQL,
            (key,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ReservationCompareAndSetError("PostgreSQL reservation record is unavailable")
        return _decode_row(row)


def reservation_storage_key(idempotency_key: str) -> str:
    """Return the canonical database key for one executor reservation."""

    if (
        type(idempotency_key) is not str
        or not idempotency_key.strip()
        or idempotency_key != idempotency_key.strip()
        or len(idempotency_key) > 512
    ):
        raise ValueError("PostgreSQL reservation idempotency key MUST be canonical and bounded")
    return _KEY_PREFIX + idempotency_key


def _decode_row(
    row: Mapping[str, object],
) -> tuple[IdempotencyReservationRecord, datetime]:
    raw_record = row.get("result")
    recorded_at = row.get("recorded_at")
    if type(raw_record) is not dict:
        raise ValueError("PostgreSQL reservation record MUST be a JSON object")
    if (
        type(recorded_at) is not datetime
        or recorded_at.tzinfo is None
        or recorded_at.utcoffset() is None
    ):
        raise ValueError("PostgreSQL reservation recorded_at MUST include a timezone")
    return (
        reservation_record_from_mapping(raw_record),
        recorded_at.astimezone(UTC),
    )


def _transition_receipt(
    *,
    prior: IdempotencyReservationRecord | None,
    record: IdempotencyReservationRecord,
    expected_prior_revision: int,
    recorded_at: datetime,
) -> IdempotencyReservationTransitionReceipt:
    store_receipt_digest = content_digest(
        {
            "domain": "postgres-idempotency-reservation-readback",
            "idempotency_key": record.identity.idempotency_key,
            "record_digest": record.record_digest,
            "revision": record.revision,
            "recorded_at": recorded_at.isoformat(),
        }
    )
    return IdempotencyReservationTransitionReceipt.create(
        prior_record=prior,
        record=record,
        expected_prior_revision=expected_prior_revision,
        store_receipt_digest=store_receipt_digest,
        recorded_at=recorded_at,
    )


__all__ = [
    "PostgresIdempotencyReservationStore",
    "PostgresIdempotencyReservationStoreConfig",
    "ReservationCompareAndSetError",
    "reservation_storage_key",
]
