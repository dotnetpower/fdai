"""PostgreSQL atomic post-release closure and quarantine reconciliation."""

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
    reservation_record_from_mapping,
    reservation_record_to_mapping,
)
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureRecord,
    audit_closure_mapping,
    closure_outbox_mapping,
)
from fdai.core.executor.post_release_closure_codec import (
    post_release_closure_from_mapping,
    post_release_closure_to_mapping,
)
from fdai.core.executor.post_release_closure_plan import PostReleaseClosurePlan
from fdai.core.executor.post_release_closure_store import (
    PostReleaseClosureStoreReceipt,
    PostReleaseClosureWriteDecision,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_dispatch_codec import (
    safeguard_dispatch_record_from_mapping,
)
from fdai.core.executor.safeguard_dispatch_support import validate_digest
from fdai.core.executor.target_dispatch_fence import TargetDispatchFenceRecord
from fdai.core.executor.target_dispatch_fence_codec import (
    target_dispatch_fence_from_mapping,
    target_dispatch_fence_to_mapping,
)
from fdai.delivery.persistence.postgres_idempotency_reservation import (
    reservation_storage_key,
)

_SELECT_CLOSURE = (
    "SELECT record, recorded_at, clock_timestamp() AS read_back_at "
    "FROM executor_post_release_closure WHERE closure_key = %s"
)
_SELECT_CLOSURE_FOR_UPDATE = _SELECT_CLOSURE + " FOR UPDATE"
_SELECT_RESERVATION_FOR_UPDATE = (
    "SELECT result, recorded_at FROM executor_idempotency_reservation "
    "WHERE idempotency_key = %s FOR UPDATE"
)
_SELECT_FENCE_FOR_UPDATE = (
    "SELECT record, recorded_at FROM target_dispatch_fence WHERE target_digest = %s FOR UPDATE"
)
_SELECT_PRE_RELEASE_FOR_UPDATE = (
    "SELECT record, recorded_at FROM safeguard_dispatch_evidence "
    "WHERE target_digest = %s AND generation = %s FOR UPDATE"
)
_UPDATE_RESERVATION = (
    "UPDATE executor_idempotency_reservation "
    "SET result = %s::jsonb, recorded_at = clock_timestamp() "
    "WHERE idempotency_key = %s AND result = %s::jsonb RETURNING recorded_at"
)
_UPDATE_FENCE = (
    "UPDATE target_dispatch_fence SET generation = %s, revision = %s, "
    "state = %s, identity_digest = %s, record_digest = %s, "
    "record = %s::jsonb, recorded_at = clock_timestamp() "
    "WHERE target_digest = %s AND revision = %s AND record_digest = %s "
    "RETURNING recorded_at"
)
_INSERT_CLOSURE = (
    "INSERT INTO executor_post_release_closure "
    "(closure_key, reservation_identity_digest, attempt, target_digest, "
    "generation, revision, outcome, identity_digest, record_digest, record) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) "
    "RETURNING recorded_at"
)
_UPDATE_CLOSURE = (
    "UPDATE executor_post_release_closure SET revision = %s, outcome = %s, "
    "record_digest = %s, record = %s::jsonb, recorded_at = clock_timestamp() "
    "WHERE closure_key = %s AND revision = %s AND record_digest = %s "
    "RETURNING recorded_at"
)
_INSERT_AUDIT = (
    "INSERT INTO executor_audit_closure "
    "(closure_key, closure_revision, audit_closure_digest, record_digest, record) "
    "VALUES (%s, %s, %s, %s, %s::jsonb) "
    "ON CONFLICT (closure_key, closure_revision) DO NOTHING"
)
_SELECT_AUDIT = (
    "SELECT record FROM executor_audit_closure WHERE closure_key = %s AND closure_revision = %s"
)
_INSERT_OUTBOX = (
    "INSERT INTO executor_post_release_outbox "
    "(event_id, closure_key, closure_revision, partition_key, payload) "
    "VALUES (%s, %s, %s, %s, %s::jsonb) ON CONFLICT (event_id) DO NOTHING"
)
_SELECT_OUTBOX = "SELECT payload FROM executor_post_release_outbox WHERE event_id = %s"


class PostReleaseClosureCompareAndSetError(RuntimeError):
    """An authoritative post-release predecessor changed before commit."""


@dataclass(frozen=True, slots=True)
class PostgresPostReleaseClosureStoreConfig:
    """Connection and statement bounds for atomic post-release closure."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresPostReleaseClosureStore:
    """Atomically close or reconcile one exact reservation and target generation."""

    production_eligible = True

    def __init__(
        self,
        *,
        config: PostgresPostReleaseClosureStoreConfig,
    ) -> None:
        if not config.dsn:
            raise ValueError("PostgresPostReleaseClosureStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    async def write(
        self,
        plan: PostReleaseClosurePlan,
    ) -> PostReleaseClosureStoreReceipt:
        if type(plan) is not PostReleaseClosurePlan:
            raise ValueError("PostgreSQL post-release closure requires an exact plan")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._prepare(connection)
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (plan.record.identity.closure_key,),
                )
                existing_row = await (
                    await connection.execute(
                        _SELECT_CLOSURE_FOR_UPDATE,
                        (plan.record.identity.closure_key,),
                    )
                ).fetchone()
                existing = _decode_optional_closure(existing_row)
                if existing is not None and existing[0] == plan.record:
                    await self._verify_terminal_readback(
                        connection,
                        plan=plan,
                    )
                    return _store_receipt(
                        record=existing[0],
                        decision=PostReleaseClosureWriteDecision.DUPLICATE_SAME,
                        persisted_at=existing[1],
                        read_back_at=existing[2],
                    )
                self._validate_closure_predecessor(existing, plan.record)
                await self._verify_predecessors(connection, plan)
                await self._write_reservation(connection, plan)
                await self._write_fence(connection, plan)
                persisted_at = await self._write_closure(
                    connection,
                    existing=existing,
                    record=plan.record,
                )
                await self._append_audit_and_outbox(connection, plan.record)
                observed, _stored_at, read_back_at = await self._read_closure_required(
                    connection,
                    plan.record.identity.closure_key,
                    for_update=True,
                )
                if observed != plan.record:
                    raise ValueError("PostgreSQL post-release closure readback mismatched")
                await self._verify_terminal_readback(connection, plan=plan)
                return _store_receipt(
                    record=observed,
                    decision=PostReleaseClosureWriteDecision.APPLIED,
                    persisted_at=persisted_at,
                    read_back_at=read_back_at,
                )

    async def read(self, closure_key: str) -> PostReleaseClosureRecord | None:
        validate_digest("closure_key", closure_key)
        async with await self._connect() as connection:
            await self._prepare(connection)
            row = await (await connection.execute(_SELECT_CLOSURE, (closure_key,))).fetchone()
            decoded = _decode_optional_closure(row)
            return decoded[0] if decoded is not None else None

    async def _verify_predecessors(
        self,
        connection: psycopg.AsyncConnection[Any],
        plan: PostReleaseClosurePlan,
    ) -> None:
        pre_release_row = await (
            await connection.execute(
                _SELECT_PRE_RELEASE_FOR_UPDATE,
                (
                    plan.record.identity.target_digest,
                    plan.record.identity.target_fence_generation,
                ),
            )
        ).fetchone()
        if _decode_pre_release(pre_release_row) != plan.pre_release_record:
            raise PostReleaseClosureCompareAndSetError(
                "PostgreSQL pre-release evidence predecessor changed"
            )
        reservation_row = await (
            await connection.execute(
                _SELECT_RESERVATION_FOR_UPDATE,
                (reservation_storage_key(plan.prior_reservation_record.identity.idempotency_key),),
            )
        ).fetchone()
        if _decode_reservation(reservation_row) != plan.prior_reservation_record:
            raise PostReleaseClosureCompareAndSetError("PostgreSQL reservation predecessor changed")
        fence_row = await (
            await connection.execute(
                _SELECT_FENCE_FOR_UPDATE,
                (plan.record.identity.target_digest,),
            )
        ).fetchone()
        if _decode_fence(fence_row) != plan.prior_fence_record:
            raise PostReleaseClosureCompareAndSetError(
                "PostgreSQL target fence predecessor changed"
            )

    async def _write_reservation(
        self,
        connection: psycopg.AsyncConnection[Any],
        plan: PostReleaseClosurePlan,
    ) -> None:
        if plan.reservation_record == plan.prior_reservation_record:
            return
        prior_json = _json(reservation_record_to_mapping(plan.prior_reservation_record))
        record_json = _json(reservation_record_to_mapping(plan.reservation_record))
        cursor = await connection.execute(
            _UPDATE_RESERVATION,
            (
                record_json,
                reservation_storage_key(plan.prior_reservation_record.identity.idempotency_key),
                prior_json,
            ),
        )
        if await cursor.fetchone() is None:
            raise PostReleaseClosureCompareAndSetError(
                "PostgreSQL reservation closure compare-and-set lost"
            )

    async def _write_fence(
        self,
        connection: psycopg.AsyncConnection[Any],
        plan: PostReleaseClosurePlan,
    ) -> None:
        record = plan.fence_record
        cursor = await connection.execute(
            _UPDATE_FENCE,
            (
                record.identity.generation,
                record.revision,
                record.state.value,
                record.identity.identity_digest,
                record.record_digest,
                _json(target_dispatch_fence_to_mapping(record)),
                record.identity.target_digest,
                plan.prior_fence_record.revision,
                plan.prior_fence_record.record_digest,
            ),
        )
        if await cursor.fetchone() is None:
            raise PostReleaseClosureCompareAndSetError(
                "PostgreSQL target fence closure compare-and-set lost"
            )

    async def _write_closure(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        existing: tuple[PostReleaseClosureRecord, datetime, datetime] | None,
        record: PostReleaseClosureRecord,
    ) -> datetime:
        mapping = _json(post_release_closure_to_mapping(record))
        if existing is None:
            cursor = await connection.execute(
                _INSERT_CLOSURE,
                (
                    record.identity.closure_key,
                    record.identity.reservation_identity_digest,
                    record.identity.reservation_attempt,
                    record.identity.target_digest,
                    record.identity.target_fence_generation,
                    record.revision,
                    record.outcome.value,
                    record.identity.identity_digest,
                    record.record_digest,
                    mapping,
                ),
            )
        else:
            cursor = await connection.execute(
                _UPDATE_CLOSURE,
                (
                    record.revision,
                    record.outcome.value,
                    record.record_digest,
                    mapping,
                    record.identity.closure_key,
                    existing[0].revision,
                    existing[0].record_digest,
                ),
            )
        row = await cursor.fetchone()
        if row is None:
            raise PostReleaseClosureCompareAndSetError(
                "PostgreSQL post-release closure compare-and-set lost"
            )
        return _row_datetime(row.get("recorded_at"), "recorded_at")

    async def _append_audit_and_outbox(
        self,
        connection: psycopg.AsyncConnection[Any],
        record: PostReleaseClosureRecord,
    ) -> None:
        audit = audit_closure_mapping(record)
        await connection.execute(
            _INSERT_AUDIT,
            (
                record.identity.closure_key,
                record.revision,
                record.audit_closure_digest,
                record.record_digest,
                _json(audit),
            ),
        )
        audit_row = await (
            await connection.execute(
                _SELECT_AUDIT,
                (record.identity.closure_key, record.revision),
            )
        ).fetchone()
        if audit_row is None or audit_row.get("record") != audit:
            raise ValueError("PostgreSQL audit closure readback mismatched")
        outbox = closure_outbox_mapping(record)
        await connection.execute(
            _INSERT_OUTBOX,
            (
                record.outbox_event_id,
                record.identity.closure_key,
                record.revision,
                record.identity.target_digest,
                _json(outbox),
            ),
        )
        outbox_row = await (
            await connection.execute(_SELECT_OUTBOX, (record.outbox_event_id,))
        ).fetchone()
        if outbox_row is None or outbox_row.get("payload") != outbox:
            raise ValueError("PostgreSQL post-release outbox readback mismatched")

    async def _verify_audit_and_outbox(
        self,
        connection: psycopg.AsyncConnection[Any],
        record: PostReleaseClosureRecord,
    ) -> None:
        audit_row = await (
            await connection.execute(
                _SELECT_AUDIT,
                (record.identity.closure_key, record.revision),
            )
        ).fetchone()
        if audit_row is None or audit_row.get("record") != audit_closure_mapping(record):
            raise ValueError("PostgreSQL audit closure readback mismatched")
        outbox_row = await (
            await connection.execute(_SELECT_OUTBOX, (record.outbox_event_id,))
        ).fetchone()
        if outbox_row is None or outbox_row.get("payload") != closure_outbox_mapping(record):
            raise ValueError("PostgreSQL post-release outbox readback mismatched")

    async def _verify_terminal_readback(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        plan: PostReleaseClosurePlan,
    ) -> None:
        pre_release_row = await (
            await connection.execute(
                _SELECT_PRE_RELEASE_FOR_UPDATE,
                (
                    plan.record.identity.target_digest,
                    plan.record.identity.target_fence_generation,
                ),
            )
        ).fetchone()
        if _decode_pre_release(pre_release_row) != plan.pre_release_record:
            raise ValueError("PostgreSQL terminal pre-release readback mismatched")
        reservation_row = await (
            await connection.execute(
                _SELECT_RESERVATION_FOR_UPDATE,
                (reservation_storage_key(plan.reservation_record.identity.idempotency_key),),
            )
        ).fetchone()
        if _decode_reservation(reservation_row) != plan.reservation_record:
            raise ValueError("PostgreSQL terminal reservation readback mismatched")
        fence_row = await (
            await connection.execute(
                _SELECT_FENCE_FOR_UPDATE,
                (plan.record.identity.target_digest,),
            )
        ).fetchone()
        if _decode_fence(fence_row) != plan.fence_record:
            raise ValueError("PostgreSQL terminal target fence readback mismatched")
        await self._verify_audit_and_outbox(connection, plan.record)

    def _validate_closure_predecessor(
        self,
        existing: tuple[PostReleaseClosureRecord, datetime, datetime] | None,
        candidate: PostReleaseClosureRecord,
    ) -> None:
        if existing is None:
            if candidate.revision != 1 or candidate.prior_record_digest is not None:
                raise PostReleaseClosureCompareAndSetError(
                    "PostgreSQL post-release initial predecessor is unavailable"
                )
            return
        current = existing[0]
        if (
            candidate.revision != current.revision + 1
            or candidate.prior_record_digest != current.record_digest
            or candidate.identity != current.identity
        ):
            raise PostReleaseClosureCompareAndSetError(
                "PostgreSQL post-release closure predecessor changed"
            )

    async def _read_closure_required(
        self,
        connection: psycopg.AsyncConnection[Any],
        closure_key: str,
        *,
        for_update: bool,
    ) -> tuple[PostReleaseClosureRecord, datetime, datetime]:
        row = await (
            await connection.execute(
                _SELECT_CLOSURE_FOR_UPDATE if for_update else _SELECT_CLOSURE,
                (closure_key,),
            )
        ).fetchone()
        decoded = _decode_optional_closure(row)
        if decoded is None:
            raise ValueError("PostgreSQL post-release closure readback is unavailable")
        return decoded

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


def _decode_optional_closure(
    row: Mapping[str, object] | None,
) -> tuple[PostReleaseClosureRecord, datetime, datetime] | None:
    if row is None:
        return None
    raw_record = row.get("record")
    if type(raw_record) is not dict:
        raise ValueError("PostgreSQL post-release closure record MUST be a JSON object")
    persisted_at = _row_datetime(row.get("recorded_at"), "recorded_at")
    read_back_raw = row.get("read_back_at")
    read_back_at = (
        _row_datetime(read_back_raw, "read_back_at") if read_back_raw is not None else persisted_at
    )
    return (
        post_release_closure_from_mapping(raw_record),
        persisted_at,
        read_back_at,
    )


def _decode_pre_release(row: Mapping[str, object] | None) -> SafeguardDispatchEvidenceRecord:
    raw = _required_record(row, "pre-release evidence")
    return safeguard_dispatch_record_from_mapping(raw)


def _decode_reservation(row: Mapping[str, object] | None) -> IdempotencyReservationRecord:
    if row is None:
        raise PostReleaseClosureCompareAndSetError(
            "PostgreSQL reservation predecessor is unavailable"
        )
    raw = row.get("result")
    if type(raw) is not dict:
        raise ValueError("PostgreSQL reservation record MUST be a JSON object")
    return reservation_record_from_mapping(raw)


def _decode_fence(row: Mapping[str, object] | None) -> TargetDispatchFenceRecord:
    raw = _required_record(row, "target fence")
    return target_dispatch_fence_from_mapping(raw)


def _required_record(
    row: Mapping[str, object] | None,
    name: str,
) -> Mapping[str, object]:
    if row is None:
        raise PostReleaseClosureCompareAndSetError(f"PostgreSQL {name} predecessor is unavailable")
    raw = row.get("record")
    if type(raw) is not dict:
        raise ValueError(f"PostgreSQL {name} record MUST be a JSON object")
    return raw


def _store_receipt(
    *,
    record: PostReleaseClosureRecord,
    decision: PostReleaseClosureWriteDecision,
    persisted_at: datetime,
    read_back_at: datetime,
) -> PostReleaseClosureStoreReceipt:
    return PostReleaseClosureStoreReceipt.create(
        decision=decision,
        record=record,
        persisted_at=persisted_at,
        read_back_at=read_back_at,
        store_receipt_digest=content_digest(
            {
                "domain": "postgres-post-release-closure-readback",
                "closure_key": record.identity.closure_key,
                "revision": record.revision,
                "record_digest": record.record_digest,
                "persisted_at": persisted_at.isoformat(),
                "read_back_at": read_back_at.isoformat(),
            }
        ),
    )


def _row_datetime(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"PostgreSQL post-release closure {name} MUST include a timezone")
    return value.astimezone(UTC)


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "PostReleaseClosureCompareAndSetError",
    "PostgresPostReleaseClosureStore",
    "PostgresPostReleaseClosureStoreConfig",
]
