"""PostgreSQL authoritative audit-intent adapter tests."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai.core.executor.audit_intent import (
    AuditIntentAppendDecision,
    PreEffectAuditIntent,
)
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    IdempotencyReservationTransitionReceipt,
)
from fdai.delivery.persistence.postgres_audit_intent import (
    PostgresAuditIntentStore,
    PostgresAuditIntentStoreConfig,
)
from fdai.shared.contracts.models import ExecutionPath
from fdai.shared.providers.resource_lock import (
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
)

_NOW = datetime(2026, 9, 10, 11, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        self._connection.commits += 1
        return False


class _Connection:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.commits = 0

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...] | None = None,
    ) -> _Cursor:
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT set_config"):
            return _Cursor(None)
        assert params is not None
        if normalized.startswith("INSERT INTO executor_audit_intent"):
            key = str(params[0])
            if key in self.rows:
                return _Cursor(None)
            self.rows[key] = {
                "intent_digest": str(params[1]),
                "record": json.loads(str(params[2])),
                "recorded_at": _NOW + timedelta(seconds=2),
                "read_back_at": _NOW + timedelta(seconds=3),
            }
            return _Cursor({"recorded_at": _NOW + timedelta(seconds=2)})
        if normalized.startswith("SELECT intent_digest"):
            if self.commits < 1:
                raise AssertionError("audit intent readback happened before insert commit")
            row = self.rows.get(str(params[0]))
            return _Cursor(dict(row) if row is not None else None)
        raise AssertionError(f"unexpected SQL: {normalized}")

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _intent(
    *,
    idempotency_key: str = "example-key",
    actor: str = "fdai.core.executor",
    now: datetime = _NOW,
    intent_delay: timedelta = timedelta(seconds=1),
) -> PreEffectAuditIntent:
    request = ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest="sha256:" + "1" * 64,
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
    reservation = IdempotencyReservationRecord.create_reserved(
        identity=identity,
        reserved_at=now,
        lease_expires_at=now + timedelta(seconds=10),
    )
    reservation_receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=None,
        record=reservation,
        expected_prior_revision=0,
        store_receipt_digest="sha256:" + "5" * 64,
        recorded_at=now,
    )
    return PreEffectAuditIntent.create(
        reservation_receipt=reservation_receipt,
        actor=actor,
        created_at=now + intent_delay,
    )


def _store(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
) -> PostgresAuditIntentStore:
    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    return PostgresAuditIntentStore(
        config=PostgresAuditIntentStoreConfig(dsn="postgresql://example"),
    )


@pytest.mark.asyncio
async def test_append_duplicate_and_conflict_are_candidate_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    intent = _intent()

    appended = await store.append_and_readback(intent)
    duplicate = await store.append_and_readback(intent)
    conflict = await store.append_and_readback(
        _intent(actor="fdai.core.other"),
    )

    assert appended.decision is AuditIntentAppendDecision.APPENDED
    assert appended.receipt is not None
    assert duplicate.decision is AuditIntentAppendDecision.DUPLICATE_SAME
    assert conflict.decision is AuditIntentAppendDecision.CONFLICT
    assert conflict.receipt is None


@pytest.mark.asyncio
async def test_readback_mismatch_returns_conflict_without_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    intent = _intent()
    appended = await store.append_and_readback(intent)
    assert appended.receipt is not None
    row = next(iter(connection.rows.values()))
    row["record"] = {"corrupt": True}

    result = await store.append_and_readback(intent)
    assert result.decision is AuditIntentAppendDecision.CONFLICT
    assert result.receipt is None


def test_config_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresAuditIntentStore(config=PostgresAuditIntentStoreConfig(dsn=""))
    with pytest.raises(ValueError, match="statement_timeout"):
        PostgresAuditIntentStore(
            config=PostgresAuditIntentStoreConfig(
                dsn="postgresql://example",
                statement_timeout_ms=0,
            )
        )


@pytest.mark.asyncio
async def test_live_postgres_append_race_and_restart() -> None:
    dsn = os.environ.get("FDAI_TEST_AUDIT_INTENT_DSN", "").strip()
    if not dsn:
        pytest.skip("FDAI_TEST_AUDIT_INTENT_DSN is not configured")
    now = datetime.now(UTC)
    intent = _intent(
        idempotency_key=f"live-{uuid4().hex}",
        now=now,
        intent_delay=timedelta(0),
    )
    config = PostgresAuditIntentStoreConfig(dsn=dsn)
    first_store = PostgresAuditIntentStore(config=config)
    second_store = PostgresAuditIntentStore(config=config)
    first, second = await asyncio.gather(
        first_store.append_and_readback(intent),
        second_store.append_and_readback(intent),
    )
    assert {first.decision, second.decision} == {
        AuditIntentAppendDecision.APPENDED,
        AuditIntentAppendDecision.DUPLICATE_SAME,
    }
    restarted = PostgresAuditIntentStore(config=config)
    duplicate = await restarted.append_and_readback(intent)
    assert duplicate.decision is AuditIntentAppendDecision.DUPLICATE_SAME
