"""PostgreSQL target-wide dispatch fence store tests."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    attach_prepared_evidence,
    resolve_target_fence_without_dispatch,
)
from fdai.core.executor.target_dispatch_fence_store import (
    TargetDispatchFenceAcquireDecision,
)
from fdai.delivery.persistence.postgres_target_dispatch_fence import (
    PostgresTargetDispatchFenceStore,
    PostgresTargetDispatchFenceStoreConfig,
    TargetDispatchFenceCompareAndSetError,
)

from tests.core.executor.test_target_dispatch_fence import (
    _DIGEST,
    _NOW,
    _audit_receipt,
    _identity,
    _preparing,
    _reservation_identity,
)


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

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...] | None = None,
    ) -> _Cursor:
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT set_config"):
            return _Cursor(None)
        assert params is not None
        if normalized.startswith("SELECT record, recorded_at"):
            row = self.rows.get(str(params[0]))
            return _Cursor(dict(row) if row is not None else None)
        if normalized.startswith("INSERT INTO target_dispatch_fence"):
            key = str(params[0])
            if key in self.rows:
                return _Cursor(None)
            self.rows[key] = {
                "record": json.loads(str(params[6])),
                "recorded_at": _NOW,
            }
            return _Cursor({"recorded_at": _NOW})
        if normalized.startswith("UPDATE target_dispatch_fence"):
            key = str(params[6])
            row = self.rows.get(key)
            if row is None:
                return _Cursor(None)
            current = row["record"]
            assert isinstance(current, dict)
            if current["revision"] != params[7] or current["record_digest"] != params[8]:
                return _Cursor(None)
            encoded = json.loads(str(params[5]))
            row["record"] = encoded
            row["recorded_at"] = datetime.fromisoformat(str(encoded["state_changed_at"]))
            return _Cursor({"recorded_at": row["recorded_at"]})
        raise AssertionError(f"unexpected SQL: {normalized}")

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _store(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
) -> PostgresTargetDispatchFenceStore:
    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    return PostgresTargetDispatchFenceStore(
        config=PostgresTargetDispatchFenceStoreConfig(
            dsn="postgresql://example",
        )
    )


@pytest.mark.asyncio
async def test_target_unique_acquire_duplicate_and_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    preparing = _preparing()

    acquired = await store.acquire_generation(preparing)
    duplicate = await store.acquire_generation(preparing)
    blocked = await store.acquire_generation(
        TargetDispatchFenceRecord.create_preparing(
            identity=_identity(
                reservation_identity=_reservation_identity(
                    attempt=2,
                    acquired_at=_NOW + timedelta(seconds=1),
                )
            ),
            changed_at=_NOW + timedelta(seconds=1),
        )
    )

    assert acquired.decision is TargetDispatchFenceAcquireDecision.ACQUIRED
    assert acquired.transition_receipt is not None
    assert duplicate.decision is TargetDispatchFenceAcquireDecision.DUPLICATE_SAME
    assert blocked.decision is TargetDispatchFenceAcquireDecision.BLOCKED


@pytest.mark.asyncio
async def test_exact_cas_and_resolved_generation_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    preparing = _preparing()
    await store.acquire_generation(preparing)
    prepared = attach_prepared_evidence(
        preparing,
        audit_append_receipt=_audit_receipt(_reservation_identity()),
        safeguard_bundle_digest="sha256:" + "7" * 64,
        changed_at=_NOW,
    )
    transition = await store.compare_and_transition(
        prior_record_digest=preparing.record_digest,
        expected_revision=preparing.revision,
        record=prepared,
    )
    assert transition.record == prepared

    resolved = resolve_target_fence_without_dispatch(
        prepared,
        no_dispatch_evidence_digest=_DIGEST,
        changed_at=_NOW + timedelta(seconds=1),
    )
    await store.compare_and_transition(
        prior_record_digest=prepared.record_digest,
        expected_revision=prepared.revision,
        record=resolved,
    )
    next_reservation = _reservation_identity(
        attempt=2,
        acquired_at=_NOW + timedelta(seconds=2),
    )
    next_record = TargetDispatchFenceRecord.create_preparing(
        identity=_identity(
            generation=2,
            reservation_identity=next_reservation,
        ),
        changed_at=_NOW + timedelta(seconds=2),
        prior_resolved_record=resolved,
    )
    acquired = await store.acquire_generation(next_record)
    assert acquired.decision is TargetDispatchFenceAcquireDecision.ACQUIRED
    assert acquired.observed_record.identity.generation == 2


@pytest.mark.asyncio
async def test_restart_read_preserves_unresolved_pre_dispatch_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    first_store = _store(monkeypatch, connection)
    preparing = _preparing()
    await first_store.acquire_generation(preparing)

    restarted = _store(monkeypatch, connection)
    assert await restarted.read(preparing.identity.target_digest) == preparing

    prepared = attach_prepared_evidence(
        preparing,
        audit_append_receipt=_audit_receipt(_reservation_identity()),
        safeguard_bundle_digest="sha256:" + "7" * 64,
        changed_at=_NOW,
    )
    await restarted.compare_and_transition(
        prior_record_digest=preparing.record_digest,
        expected_revision=preparing.revision,
        record=prepared,
    )

    restarted_again = _store(monkeypatch, connection)
    assert await restarted_again.read(prepared.identity.target_digest) == prepared


@pytest.mark.asyncio
async def test_stale_cas_and_corrupt_readback_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    preparing = _preparing()
    await store.acquire_generation(preparing)

    with pytest.raises(TargetDispatchFenceCompareAndSetError):
        await store.compare_and_transition(
            prior_record_digest="sha256:" + "0" * 64,
            expected_revision=preparing.revision,
            record=resolve_target_fence_without_dispatch(
                preparing,
                no_dispatch_evidence_digest=_DIGEST,
                changed_at=_NOW,
            ),
        )
    row = next(iter(connection.rows.values()))
    row["record"] = {"corrupt": True}
    with pytest.raises(ValueError):
        await store.read(preparing.identity.target_digest)


def test_config_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresTargetDispatchFenceStore(
            config=PostgresTargetDispatchFenceStoreConfig(dsn=""),
        )
    with pytest.raises(ValueError, match="statement_timeout"):
        PostgresTargetDispatchFenceStore(
            config=PostgresTargetDispatchFenceStoreConfig(
                dsn="postgresql://example",
                statement_timeout_ms=0,
            )
        )


@pytest.mark.asyncio
async def test_live_postgres_target_contention_restart_and_generation_cas() -> None:
    dsn = os.environ.get("FDAI_TEST_TARGET_FENCE_DSN", "").strip()
    if not dsn:
        pytest.skip("FDAI_TEST_TARGET_FENCE_DSN is not configured")
    now = datetime.now(UTC)
    target = f"resource/live-fence-{os.getpid()}"
    reservation = _reservation_identity(
        target_ref=target,
        acquired_at=now,
    )
    preparing = TargetDispatchFenceRecord.create_preparing(
        identity=_identity(reservation_identity=reservation),
        changed_at=now,
    )
    config = PostgresTargetDispatchFenceStoreConfig(dsn=dsn)
    first_store = PostgresTargetDispatchFenceStore(config=config)
    second_store = PostgresTargetDispatchFenceStore(config=config)

    first, second = await asyncio.gather(
        first_store.acquire_generation(preparing),
        second_store.acquire_generation(preparing),
    )
    assert {first.decision, second.decision} == {
        TargetDispatchFenceAcquireDecision.ACQUIRED,
        TargetDispatchFenceAcquireDecision.DUPLICATE_SAME,
    }

    resolved = resolve_target_fence_without_dispatch(
        preparing,
        no_dispatch_evidence_digest=_DIGEST,
        changed_at=now + timedelta(microseconds=1),
    )
    await first_store.compare_and_transition(
        prior_record_digest=preparing.record_digest,
        expected_revision=preparing.revision,
        record=resolved,
    )
    restarted = PostgresTargetDispatchFenceStore(config=config)
    assert await restarted.read(preparing.identity.target_digest) == resolved
