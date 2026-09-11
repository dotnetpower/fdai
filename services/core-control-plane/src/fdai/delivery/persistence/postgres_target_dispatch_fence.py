"""PostgreSQL target-wide dispatch fence store."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.ontology_query import content_digest
from psycopg.rows import dict_row

from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
    TargetDispatchFenceTransitionReceipt,
)
from fdai.core.executor.target_dispatch_fence_codec import (
    target_dispatch_fence_from_mapping,
    target_dispatch_fence_to_mapping,
)
from fdai.core.executor.target_dispatch_fence_store import (
    TargetDispatchFenceAcquireDecision,
    TargetDispatchFenceAcquireResult,
    classify_target_fence,
)

_SELECT_SQL = "SELECT record, recorded_at FROM target_dispatch_fence WHERE target_digest = %s"
_SELECT_FOR_UPDATE_SQL = _SELECT_SQL + " FOR UPDATE"
_INSERT_SQL = (
    "INSERT INTO target_dispatch_fence "
    "(target_digest, generation, revision, state, identity_digest, "
    "record_digest, record) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) "
    "ON CONFLICT (target_digest) DO NOTHING "
    "RETURNING recorded_at"
)
_UPDATE_SQL = (
    "UPDATE target_dispatch_fence SET generation = %s, revision = %s, "
    "state = %s, identity_digest = %s, record_digest = %s, "
    "record = %s::jsonb, recorded_at = clock_timestamp() "
    "WHERE target_digest = %s AND revision = %s AND record_digest = %s "
    "RETURNING recorded_at"
)


class TargetDispatchFenceCompareAndSetError(RuntimeError):
    """The authoritative target fence changed before compare-and-set."""


@dataclass(frozen=True, slots=True)
class PostgresTargetDispatchFenceStoreConfig:
    """Connection and statement bounds for the target fence store."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresTargetDispatchFenceStore:
    """Target-unique generation acquisition and exact-record CAS."""

    production_eligible = True

    def __init__(
        self,
        *,
        config: PostgresTargetDispatchFenceStoreConfig,
    ) -> None:
        if not config.dsn:
            raise ValueError("PostgresTargetDispatchFenceStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    async def acquire_generation(
        self,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceAcquireResult:
        if (
            type(record) is not TargetDispatchFenceRecord
            or record.state is not TargetDispatchFenceState.PREPARING
        ):
            raise ValueError("PostgreSQL target fence acquisition requires preparing state")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                existing_row = await (
                    await connection.execute(
                        _SELECT_FOR_UPDATE_SQL,
                        (record.identity.target_digest,),
                    )
                ).fetchone()
                existing = _decode_optional_record(existing_row)
                if existing is not None:
                    decision = classify_target_fence(existing, record.identity)
                    if decision is TargetDispatchFenceAcquireDecision.DUPLICATE_SAME:
                        return TargetDispatchFenceAcquireResult(
                            candidate_identity=record.identity,
                            decision=decision,
                            observed_record=existing,
                            transition_receipt=None,
                        )
                    if (
                        existing.state is not TargetDispatchFenceState.RESOLVED
                        or record.prior_record_digest != existing.record_digest
                        or record.revision != existing.revision + 1
                        or record.identity.generation != existing.identity.generation + 1
                    ):
                        return TargetDispatchFenceAcquireResult(
                            candidate_identity=record.identity,
                            decision=TargetDispatchFenceAcquireDecision.BLOCKED,
                            observed_record=existing,
                            transition_receipt=None,
                        )
                    updated_at = await self._update(
                        connection,
                        prior=existing,
                        record=record,
                    )
                    observed, read_at = await self._read_required(
                        connection,
                        record.identity.target_digest,
                        for_update=True,
                    )
                    if observed != record:
                        raise ValueError("PostgreSQL target fence generation readback mismatched")
                    transition = _transition_receipt(
                        prior=existing,
                        record=observed,
                        recorded_at=max(updated_at, read_at),
                    )
                    return TargetDispatchFenceAcquireResult(
                        candidate_identity=record.identity,
                        decision=TargetDispatchFenceAcquireDecision.ACQUIRED,
                        observed_record=observed,
                        transition_receipt=transition,
                    )
                inserted_at = await self._insert(connection, record)
                observed, read_at = await self._read_required(
                    connection,
                    record.identity.target_digest,
                    for_update=True,
                )
                if inserted_at is None:
                    return TargetDispatchFenceAcquireResult(
                        candidate_identity=record.identity,
                        decision=classify_target_fence(
                            observed,
                            record.identity,
                        ),
                        observed_record=observed,
                        transition_receipt=None,
                    )
                if observed != record:
                    raise ValueError("PostgreSQL target fence insert readback mismatched")
                transition = _transition_receipt(
                    prior=None,
                    record=observed,
                    recorded_at=max(inserted_at, read_at),
                )
                return TargetDispatchFenceAcquireResult(
                    candidate_identity=record.identity,
                    decision=TargetDispatchFenceAcquireDecision.ACQUIRED,
                    observed_record=observed,
                    transition_receipt=transition,
                )

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceTransitionReceipt:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                prior, _read_at = await self._read_required(
                    connection,
                    record.identity.target_digest,
                    for_update=True,
                )
                if (
                    prior.record_digest != prior_record_digest
                    or prior.revision != expected_revision
                ):
                    raise TargetDispatchFenceCompareAndSetError(
                        "PostgreSQL target fence predecessor changed"
                    )
                updated_at = await self._update(
                    connection,
                    prior=prior,
                    record=record,
                )
                observed, read_at = await self._read_required(
                    connection,
                    record.identity.target_digest,
                    for_update=True,
                )
                if observed != record:
                    raise ValueError("PostgreSQL target fence update readback mismatched")
                return _transition_receipt(
                    prior=prior,
                    record=observed,
                    recorded_at=max(updated_at, read_at),
                )

    async def read(
        self,
        target_digest: str,
    ) -> TargetDispatchFenceRecord | None:
        async with await self._connect() as connection:
            await self._set_statement_timeout(connection)
            cursor = await connection.execute(_SELECT_SQL, (target_digest,))
            return _decode_optional_record(await cursor.fetchone())

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=False,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_statement_timeout(
        self,
        connection: psycopg.AsyncConnection[Any],
    ) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )

    async def _insert(
        self,
        connection: psycopg.AsyncConnection[Any],
        record: TargetDispatchFenceRecord,
    ) -> datetime | None:
        cursor = await connection.execute(
            _INSERT_SQL,
            _record_params(record),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_datetime(row.get("recorded_at"))

    async def _update(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        prior: TargetDispatchFenceRecord,
        record: TargetDispatchFenceRecord,
    ) -> datetime:
        cursor = await connection.execute(
            _UPDATE_SQL,
            (
                record.identity.generation,
                record.revision,
                record.state.value,
                record.identity.identity_digest,
                record.record_digest,
                _encoded_record(record),
                record.identity.target_digest,
                prior.revision,
                prior.record_digest,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            raise TargetDispatchFenceCompareAndSetError(
                "PostgreSQL target fence compare-and-set lost"
            )
        return _row_datetime(row.get("recorded_at"))

    async def _read_required(
        self,
        connection: psycopg.AsyncConnection[Any],
        target_digest: str,
        *,
        for_update: bool,
    ) -> tuple[TargetDispatchFenceRecord, datetime]:
        cursor = await connection.execute(
            _SELECT_FOR_UPDATE_SQL if for_update else _SELECT_SQL,
            (target_digest,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise TargetDispatchFenceCompareAndSetError("PostgreSQL target fence is unavailable")
        record = _decode_optional_record(row)
        if record is None:
            raise TargetDispatchFenceCompareAndSetError("PostgreSQL target fence is unavailable")
        return record, _row_datetime(row.get("recorded_at"))


def _record_params(record: TargetDispatchFenceRecord) -> tuple[object, ...]:
    return (
        record.identity.target_digest,
        record.identity.generation,
        record.revision,
        record.state.value,
        record.identity.identity_digest,
        record.record_digest,
        _encoded_record(record),
    )


def _encoded_record(record: TargetDispatchFenceRecord) -> str:
    return json.dumps(
        target_dispatch_fence_to_mapping(record),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_optional_record(
    row: Mapping[str, object] | None,
) -> TargetDispatchFenceRecord | None:
    if row is None:
        return None
    raw = row.get("record")
    if type(raw) is not dict:
        raise ValueError("PostgreSQL target fence record MUST be a JSON object")
    return target_dispatch_fence_from_mapping(raw)


def _row_datetime(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("PostgreSQL target fence recorded_at MUST include a timezone")
    return value.astimezone(UTC)


def _transition_receipt(
    *,
    prior: TargetDispatchFenceRecord | None,
    record: TargetDispatchFenceRecord,
    recorded_at: datetime,
) -> TargetDispatchFenceTransitionReceipt:
    return TargetDispatchFenceTransitionReceipt.create(
        prior_record=prior,
        record=record,
        store_receipt_digest=content_digest(
            {
                "domain": "postgres-target-dispatch-fence-readback",
                "target_digest": record.identity.target_digest,
                "generation": record.identity.generation,
                "revision": record.revision,
                "record_digest": record.record_digest,
                "recorded_at": recorded_at.isoformat(),
            }
        ),
        recorded_at=recorded_at,
    )


__all__ = [
    "PostgresTargetDispatchFenceStore",
    "PostgresTargetDispatchFenceStoreConfig",
    "TargetDispatchFenceCompareAndSetError",
]
