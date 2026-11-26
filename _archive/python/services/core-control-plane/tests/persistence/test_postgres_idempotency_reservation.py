"""PostgreSQL idempotency reservation adapter tests."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    ReservationMatch,
    begin_dispatch,
)
from fdai.delivery.persistence.postgres_idempotency_reservation import (
    PostgresIdempotencyReservationStore,
    PostgresIdempotencyReservationStoreConfig,
    ReservationCompareAndSetError,
)
from fdai.shared.contracts.models import ExecutionPath
from fdai.shared.providers.resource_lock import (
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
)

_NOW = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Connection:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.executed: list[str] = []

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...] | None = None,
    ) -> _Cursor:
        normalized = " ".join(sql.split())
        self.executed.append(normalized)
        if normalized.startswith("SELECT set_config"):
            return _Cursor(None)
        assert params is not None
        if normalized.startswith("INSERT INTO executor_idempotency_reservation"):
            key = str(params[0])
            if key in self.rows:
                return _Cursor(None)
            self.rows[key] = {
                "result": json.loads(str(params[1])),
                "recorded_at": _NOW,
            }
            return _Cursor({"recorded_at": _NOW})
        if normalized.startswith("UPDATE executor_idempotency_reservation"):
            key = str(params[1])
            current = self.rows.get(key)
            if current is None or current["result"] != json.loads(str(params[2])):
                return _Cursor(None)
            current["result"] = json.loads(str(params[0]))
            current["recorded_at"] = _NOW + timedelta(seconds=2)
            return _Cursor({"recorded_at": current["recorded_at"]})
        if normalized.startswith("SELECT result, recorded_at"):
            return _Cursor(self.rows.get(str(params[0])))
        raise AssertionError(f"unexpected SQL: {normalized}")

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _record(
    *,
    action_digest: str = "sha256:" + "1" * 64,
    idempotency_key: str = "example-key",
    now: datetime = _NOW,
) -> IdempotencyReservationRecord:
    request = ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest=action_digest,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "a" * 40,
    )
    acquisition = ResourceLockAcquisitionReceipt.create(
        lock_key=request.lock_key,
        target_digest=request.target_digest,
        action_digest=request.action_digest,
        attempt=request.attempt,
        provider_id="postgres-advisory-lock",
        provider_version="1.0.0",
        producer_id=request.producer_id,
        producer_version=request.producer_version,
        owner_token_digest="sha256:" + "2" * 64,
        fencing_generation=1,
        session_identity=None,
        provider_attestation_digest="sha256:" + "3" * 64,
        trust_anchor_id="postgres:primary",
        acquired_at=now,
        valid_until=now + timedelta(minutes=1),
        source_revision=request.source_revision,
        request_digest=request.request_digest,
    )
    identity = IdempotencyReservationIdentity.create(
        idempotency_key=idempotency_key,
        action_digest=request.action_digest,
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint="4" * 64,
        source_revision=request.source_revision,
        acquisition_receipt=acquisition,
    )
    return IdempotencyReservationRecord.create_reserved(
        identity=identity,
        reserved_at=now,
        lease_expires_at=now + timedelta(seconds=10),
    )


def _store(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
) -> PostgresIdempotencyReservationStore:
    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    return PostgresIdempotencyReservationStore(
        config=PostgresIdempotencyReservationStoreConfig(
            dsn="postgresql://example",
        )
    )


@pytest.mark.asyncio
async def test_atomic_reserve_distinguishes_insert_duplicate_and_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    record = _record()

    inserted = await store.reserve(record)
    duplicate = await store.reserve(record)
    conflict = await store.reserve(_record(action_digest="sha256:" + "9" * 64))

    assert inserted.match is ReservationMatch.ACQUIRED
    assert inserted.transition_receipt is not None
    assert duplicate.match is ReservationMatch.DUPLICATE_SAME
    assert duplicate.transition_receipt is None
    assert conflict.match is ReservationMatch.CONFLICT
    assert any("executor_idempotency_reservation" in statement for statement in connection.executed)
    assert not any(" action_idempotency " in statement for statement in connection.executed)


@pytest.mark.asyncio
async def test_compare_and_transition_reads_back_exact_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    reserved = _record()
    await store.reserve(reserved)
    in_flight = begin_dispatch(reserved, at=_NOW + timedelta(seconds=1))

    receipt = await store.compare_and_transition(
        prior_record_digest=reserved.record_digest,
        expected_prior_revision=reserved.revision,
        record=in_flight,
    )

    assert receipt.prior_record == reserved
    assert receipt.record == in_flight
    assert await store.read("example-key") == in_flight


@pytest.mark.asyncio
async def test_compare_and_transition_rejects_stale_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    reserved = _record()
    await store.reserve(reserved)

    with pytest.raises(ReservationCompareAndSetError, match="predecessor changed"):
        await store.compare_and_transition(
            prior_record_digest="sha256:" + "0" * 64,
            expected_prior_revision=reserved.revision,
            record=begin_dispatch(reserved, at=_NOW + timedelta(seconds=1)),
        )


@pytest.mark.asyncio
async def test_adapter_never_runs_runtime_ddl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    reserved = _record()
    assert (await store.reserve(reserved)).match is ReservationMatch.ACQUIRED
    assert not any(statement.startswith("CREATE TABLE") for statement in connection.executed)


def test_config_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresIdempotencyReservationStore(
            config=PostgresIdempotencyReservationStoreConfig(dsn=""),
        )
    with pytest.raises(ValueError, match="statement_timeout"):
        PostgresIdempotencyReservationStore(
            config=PostgresIdempotencyReservationStoreConfig(
                dsn="postgresql://example",
                statement_timeout_ms=0,
            )
        )


@pytest.mark.asyncio
async def test_live_postgres_race_restart_and_stale_cas() -> None:
    dsn = os.environ.get("FDAI_TEST_RESERVATION_DSN", "").strip()
    if not dsn:
        pytest.skip("FDAI_TEST_RESERVATION_DSN is not configured")
    key = f"live-{uuid4().hex}"
    reserved = _record(idempotency_key=key, now=datetime.now(UTC))
    config = PostgresIdempotencyReservationStoreConfig(dsn=dsn)
    first_store = PostgresIdempotencyReservationStore(config=config)
    second_store = PostgresIdempotencyReservationStore(config=config)

    first, second = await asyncio.gather(
        first_store.reserve(reserved),
        second_store.reserve(reserved),
    )
    assert {first.match, second.match} == {
        ReservationMatch.ACQUIRED,
        ReservationMatch.DUPLICATE_SAME,
    }

    in_flight = begin_dispatch(reserved, at=datetime.now(UTC))
    transition = await second_store.compare_and_transition(
        prior_record_digest=reserved.record_digest,
        expected_prior_revision=reserved.revision,
        record=in_flight,
    )
    assert transition.record == in_flight

    restarted = PostgresIdempotencyReservationStore(config=config)
    assert await restarted.read(key) == in_flight
    with pytest.raises(ReservationCompareAndSetError):
        await first_store.compare_and_transition(
            prior_record_digest=reserved.record_digest,
            expected_prior_revision=reserved.revision,
            record=in_flight,
        )
