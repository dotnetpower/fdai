"""PostgreSQL store for safeguard dispatch and pre-release evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.ontology_query import content_digest
from psycopg.rows import dict_row

from fdai.core.executor.safeguard_dispatch_checkpoint import (
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_codec import (
    safeguard_dispatch_record_from_mapping,
    safeguard_dispatch_record_to_mapping,
)
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchPersistenceDecision,
    SafeguardDispatchPersistenceResult,
    SafeguardDispatchTransitionReceipt,
    classify_safeguard_dispatch_evidence,
)
from fdai.core.executor.safeguard_dispatch_support import validate_digest
from fdai.core.executor.safeguard_dispatch_transition import (
    validate_dispatch_evidence_transition,
)
from fdai.shared.providers.resource_lock import LiveLockOwnershipAssessment

_SELECT_SQL = (
    "SELECT record, recorded_at FROM safeguard_dispatch_evidence "
    "WHERE target_digest = %s AND generation = %s"
)
_SELECT_FOR_UPDATE_SQL = _SELECT_SQL + " FOR UPDATE"
_INSERT_SQL = (
    "INSERT INTO safeguard_dispatch_evidence "
    "(target_digest, generation, revision, state, evidence_identity_digest, "
    "record_digest, record) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) "
    "ON CONFLICT (target_digest, generation) DO NOTHING "
    "RETURNING recorded_at"
)
_UPDATE_SQL = (
    "UPDATE safeguard_dispatch_evidence SET revision = %s, state = %s, "
    "evidence_identity_digest = %s, record_digest = %s, record = %s::jsonb, "
    "recorded_at = clock_timestamp() "
    "WHERE target_digest = %s AND generation = %s "
    "AND revision = %s AND record_digest = %s RETURNING recorded_at"
)


class SafeguardDispatchCompareAndSetError(RuntimeError):
    """The authoritative safeguard evidence changed before compare-and-set."""


@dataclass(frozen=True, slots=True)
class PostgresSafeguardDispatchEvidenceStoreConfig:
    """Connection and statement bounds for safeguard dispatch persistence."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresSafeguardDispatchEvidenceStore:
    """Generation-unique insert, exact-record CAS, and strict readback."""

    production_eligible = True

    def __init__(
        self,
        *,
        config: PostgresSafeguardDispatchEvidenceStoreConfig,
    ) -> None:
        if not config.dsn:
            raise ValueError("PostgresSafeguardDispatchEvidenceStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    async def persist_bundle(
        self,
        record: SafeguardDispatchEvidenceRecord,
    ) -> SafeguardDispatchPersistenceResult:
        if (
            type(record) is not SafeguardDispatchEvidenceRecord
            or record.state is not SafeguardDispatchEvidenceState.BUNDLE_PERSISTED
            or record.revision != 1
            or record.prior_record_digest is not None
        ):
            raise ValueError(
                "PostgreSQL safeguard dispatch insert requires revision-one bundle evidence"
            )
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                cursor = await connection.execute(
                    _INSERT_SQL,
                    _record_params(record),
                )
                inserted = await cursor.fetchone()
                observed, recorded_at = await self._read_required(
                    connection,
                    record.identity.target_digest,
                    record.identity.target_fence_generation,
                    for_update=True,
                )
                if inserted is None:
                    return SafeguardDispatchPersistenceResult(
                        candidate_identity=record.identity,
                        decision=classify_safeguard_dispatch_evidence(
                            observed,
                            record.identity,
                        ),
                        observed_record=observed,
                        transition_receipt=None,
                    )
                inserted_at = _row_datetime(inserted.get("recorded_at"))
                if observed != record:
                    raise ValueError(
                        "PostgreSQL safeguard dispatch insert readback mismatched candidate"
                    )
                receipt = _transition_receipt(
                    prior=None,
                    record=observed,
                    recorded_at=max(inserted_at, recorded_at),
                )
                return SafeguardDispatchPersistenceResult(
                    candidate_identity=record.identity,
                    decision=SafeguardDispatchPersistenceDecision.PERSISTED,
                    observed_record=observed,
                    transition_receipt=receipt,
                )

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: SafeguardDispatchEvidenceRecord,
        bundle_persistence_receipt: SafeguardDispatchTransitionReceipt | None = None,
        current_lock_assessment: LiveLockOwnershipAssessment | None = None,
    ) -> SafeguardDispatchTransitionReceipt:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                prior, _prior_read_at = await self._read_required(
                    connection,
                    record.identity.target_digest,
                    record.identity.target_fence_generation,
                    for_update=True,
                )
                if (
                    prior.record_digest != prior_record_digest
                    or prior.revision != expected_revision
                ):
                    raise SafeguardDispatchCompareAndSetError(
                        "PostgreSQL safeguard dispatch predecessor changed"
                    )
                validate_dispatch_evidence_transition(
                    prior,
                    record,
                    current_lock_assessment=current_lock_assessment,
                )
                if record.state is SafeguardDispatchEvidenceState.DISPATCH_STARTED:
                    start = record.dispatch_start_checkpoint
                    if (
                        type(bundle_persistence_receipt) is not SafeguardDispatchTransitionReceipt
                        or bundle_persistence_receipt.prior_record is not None
                        or bundle_persistence_receipt.record != prior
                        or start is None
                        or start.bundle_persistence_receipt_digest
                        != bundle_persistence_receipt.receipt_digest
                    ):
                        raise ValueError(
                            "PostgreSQL dispatch-start CAS requires bundle persistence receipt"
                        )
                elif bundle_persistence_receipt is not None:
                    raise ValueError("PostgreSQL non-start CAS received bundle persistence receipt")
                updated_at = await self._update(
                    connection,
                    prior=prior,
                    record=record,
                )
                observed, read_at = await self._read_required(
                    connection,
                    record.identity.target_digest,
                    record.identity.target_fence_generation,
                    for_update=True,
                )
                if observed != record:
                    raise ValueError(
                        "PostgreSQL safeguard dispatch update readback mismatched candidate"
                    )
                return _transition_receipt(
                    prior=prior,
                    record=observed,
                    bundle_persistence_receipt=bundle_persistence_receipt,
                    current_lock_assessment=current_lock_assessment,
                    recorded_at=max(updated_at, read_at),
                )

    async def read(
        self,
        target_digest: str,
        generation: int,
    ) -> SafeguardDispatchEvidenceRecord | None:
        _validate_storage_key(target_digest, generation)
        async with await self._connect() as connection:
            await self._set_statement_timeout(connection)
            cursor = await connection.execute(
                _SELECT_SQL,
                (target_digest, generation),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            record, _recorded_at = _decode_row(row)
            if (
                record.identity.target_digest != target_digest
                or record.identity.target_fence_generation != generation
            ):
                raise ValueError("PostgreSQL safeguard dispatch readback key mismatched")
            return record

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

    async def _update(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        prior: SafeguardDispatchEvidenceRecord,
        record: SafeguardDispatchEvidenceRecord,
    ) -> datetime:
        cursor = await connection.execute(
            _UPDATE_SQL,
            (
                record.revision,
                record.state.value,
                record.identity.identity_digest,
                record.record_digest,
                _encoded_record(record),
                record.identity.target_digest,
                record.identity.target_fence_generation,
                prior.revision,
                prior.record_digest,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            raise SafeguardDispatchCompareAndSetError(
                "PostgreSQL safeguard dispatch compare-and-set lost"
            )
        return _row_datetime(row.get("recorded_at"))

    async def _read_required(
        self,
        connection: psycopg.AsyncConnection[Any],
        target_digest: str,
        generation: int,
        *,
        for_update: bool,
    ) -> tuple[SafeguardDispatchEvidenceRecord, datetime]:
        _validate_storage_key(target_digest, generation)
        cursor = await connection.execute(
            _SELECT_FOR_UPDATE_SQL if for_update else _SELECT_SQL,
            (target_digest, generation),
        )
        row = await cursor.fetchone()
        if row is None:
            raise SafeguardDispatchCompareAndSetError(
                "PostgreSQL safeguard dispatch evidence is unavailable"
            )
        record, recorded_at = _decode_row(row)
        if (
            record.identity.target_digest != target_digest
            or record.identity.target_fence_generation != generation
        ):
            raise ValueError("PostgreSQL safeguard dispatch readback key mismatched")
        return record, recorded_at


def _record_params(record: SafeguardDispatchEvidenceRecord) -> tuple[object, ...]:
    return (
        record.identity.target_digest,
        record.identity.target_fence_generation,
        record.revision,
        record.state.value,
        record.identity.identity_digest,
        record.record_digest,
        _encoded_record(record),
    )


def _encoded_record(record: SafeguardDispatchEvidenceRecord) -> str:
    return json.dumps(
        safeguard_dispatch_record_to_mapping(record),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_row(
    row: Mapping[str, object],
) -> tuple[SafeguardDispatchEvidenceRecord, datetime]:
    raw_record = row.get("record")
    if type(raw_record) is not dict:
        raise ValueError("PostgreSQL safeguard dispatch record MUST be a JSON object")
    return (
        safeguard_dispatch_record_from_mapping(raw_record),
        _row_datetime(row.get("recorded_at")),
    )


def _row_datetime(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("PostgreSQL safeguard dispatch recorded_at MUST include a timezone")
    return value.astimezone(UTC)


def _validate_storage_key(target_digest: str, generation: int) -> None:
    validate_digest("target_digest", target_digest)
    if type(generation) is not int or generation < 1:
        raise ValueError("PostgreSQL safeguard dispatch generation MUST be positive")


def _transition_receipt(
    *,
    prior: SafeguardDispatchEvidenceRecord | None,
    record: SafeguardDispatchEvidenceRecord,
    bundle_persistence_receipt: SafeguardDispatchTransitionReceipt | None = None,
    current_lock_assessment: LiveLockOwnershipAssessment | None = None,
    recorded_at: datetime,
) -> SafeguardDispatchTransitionReceipt:
    return SafeguardDispatchTransitionReceipt.create(
        prior_record=prior,
        record=record,
        bundle_persistence_receipt=bundle_persistence_receipt,
        current_lock_assessment=current_lock_assessment,
        store_receipt_digest=content_digest(
            {
                "domain": "postgres-safeguard-dispatch-readback",
                "target_digest": record.identity.target_digest,
                "generation": record.identity.target_fence_generation,
                "revision": record.revision,
                "record_digest": record.record_digest,
                "recorded_at": recorded_at.isoformat(),
            }
        ),
        recorded_at=recorded_at,
    )


__all__ = [
    "PostgresSafeguardDispatchEvidenceStore",
    "PostgresSafeguardDispatchEvidenceStoreConfig",
    "SafeguardDispatchCompareAndSetError",
]
