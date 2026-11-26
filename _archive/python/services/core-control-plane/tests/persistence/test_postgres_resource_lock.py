"""Unit tests for PostgresAdvisoryResourceLock + the ResourceLock seam.

The lock/unlock SQL flow is exercised against a fake psycopg connection
so the adapter has coverage without a live database; the in-memory and
Postgres implementations are both asserted to satisfy the ResourceLock
Protocol.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
    ResourceLockOwnershipUnknownError,
    ResourceLockReleaseUnknownError,
)
from fdai.shared.providers.resource_lock import (
    EvidenceResourceLock,
    ResourceLock,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseState,
    require_evidence_resource_lock,
)

_NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


class _FakeCursor:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, object] | None:
        return self._row


class _FakeConn:
    def __init__(
        self,
        *,
        owns_lock: bool = True,
        released: bool = True,
        readback_backend_pid: int = 42,
        cancel_readback: bool = False,
        evaluated_at: datetime = _NOW + timedelta(seconds=1),
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.owns_lock = owns_lock
        self.released = released
        self.readback_backend_pid = readback_backend_pid
        self.cancel_readback = cancel_readback
        self.evaluated_at = evaluated_at

    async def execute(self, sql: str, params: Any = None) -> _FakeCursor:
        self.calls.append((sql, params))
        if "FROM pg_locks" in sql:
            if self.cancel_readback:
                raise asyncio.CancelledError
            return _FakeCursor(
                {
                    "owns_lock": self.owns_lock,
                    "database_name": "fdai",
                    "backend_pid": self.readback_backend_pid,
                    "backend_start": _NOW - timedelta(minutes=1),
                    "evaluated_at": self.evaluated_at,
                }
            )
        if "FROM pg_stat_activity" in sql:
            return _FakeCursor(
                {
                    "database_name": "fdai",
                    "backend_pid": 42,
                    "backend_start": _NOW - timedelta(minutes=1),
                    "observed_at": _NOW,
                }
            )
        if "AS released" in sql:
            return _FakeCursor(
                {
                    "released": self.released,
                    "released_at": _NOW + timedelta(seconds=2),
                }
            )
        return _FakeCursor()

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def test_in_memory_manager_satisfies_protocol() -> None:
    assert isinstance(ResourceLockManager(), ResourceLock)


def test_postgres_lock_satisfies_protocol() -> None:
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://x")
    )
    assert isinstance(lock, ResourceLock)


def _request() -> ResourceLockAcquisitionRequest:
    return ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest="sha256:" + "1" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "a" * 40,
    )


def _policy() -> EffectSinkContinuityPolicy:
    return EffectSinkContinuityPolicy.create(
        sink_id="direct-api-example",
        sink_version="1.0.0",
        strategy=OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION,
        cancellation_supported=True,
        durable_unknown_quarantine=True,
        reconciliation_supported=True,
    )


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresAdvisoryResourceLock(config=PostgresAdvisoryResourceLockConfig(dsn=""))


def test_config_rejects_negative_timeout() -> None:
    with pytest.raises(ValueError, match="lock_timeout_ms"):
        PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://x", lock_timeout_ms=-1)
        )


def test_acquire_issues_lock_and_unlock(monkeypatch: pytest.MonkeyPatch) -> None:
    conns: list[_FakeConn] = []

    async def _connect(_dsn: str, autocommit: bool = False, **_kwargs: object) -> _FakeConn:
        conn = _FakeConn()
        conns.append(conn)
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://x", lock_timeout_ms=5000)
    )

    async def _use() -> None:
        async with lock.acquire("vm-1"):
            pass

    asyncio.run(_use())

    assert len(conns) == 1
    sqls = [c[0] for c in conns[0].calls]
    assert any("set_config" in s for s in sqls)  # lock_timeout bounded
    assert any("pg_advisory_lock" in s for s in sqls)
    assert any("pg_advisory_unlock" in s for s in sqls)
    lock_call = next(c for c in conns[0].calls if "pg_advisory_lock" in c[0])
    assert lock_call[1] == ("vm-1",)


def test_acquire_skips_timeout_when_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    conns: list[_FakeConn] = []

    async def _connect(_dsn: str, autocommit: bool = False, **_kwargs: object) -> _FakeConn:
        conn = _FakeConn()
        conns.append(conn)
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://x", lock_timeout_ms=0)
    )

    async def _use() -> None:
        async with lock.acquire("vm-2"):
            pass

    asyncio.run(_use())
    sqls = [c[0] for c in conns[0].calls]
    assert not any("set_config" in s for s in sqls)  # no timeout -> wait forever


def test_evidenced_acquisition_uses_exact_session_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()

    async def _connect(*_args: object, **_kwargs: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(
            dsn="postgresql://private-example",
            continuity_policy=_policy(),
        )
    )

    async def _use() -> None:
        async with lock.acquire_evidenced(_request()) as held:
            assessment = await held.assess_ownership()
            assert assessment.eligible is True
            assert assessment.execution_authority is False
            assert "private-example" not in repr(held.acquisition_receipt)
            assert held.release_receipt is None
        with pytest.raises(RuntimeError, match="no longer active"):
            held.require_active()
        assert held.release_receipt is not None
        assert held.release_receipt.state is ResourceLockReleaseState.RELEASED

    asyncio.run(_use())

    assert isinstance(lock, EvidenceResourceLock)
    assert require_evidence_resource_lock(lock, production=True) is lock
    assert any("pg_stat_activity" in sql for sql, _ in conn.calls)
    assert any("pg_locks" in sql for sql, _ in conn.calls)


def test_evidenced_acquisition_reports_lock_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(owns_lock=False)

    async def _connect(*_args: object, **_kwargs: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://example")
    )

    async def _use() -> None:
        held = None
        with pytest.raises(ResourceLockReleaseUnknownError):
            async with lock.acquire_evidenced(_request()) as held:
                assert (await held.assess_ownership()).eligible is False
                with pytest.raises(RuntimeError, match="no longer active"):
                    held.require_active()
        assert held is not None
        assert held.release_receipt is not None
        assert held.release_receipt.state is ResourceLockReleaseState.UNKNOWN

    asyncio.run(_use())
    with pytest.raises(RuntimeError, match="not production eligible"):
        require_evidence_resource_lock(lock, production=True)


def test_production_gate_rejects_incompatible_session_policy() -> None:
    fenced_policy = EffectSinkContinuityPolicy.create(
        sink_id="fenced-example",
        sink_version="1.0.0",
        strategy=OwnershipContinuityStrategy.FENCED_IDEMPOTENT,
        sink_fencing=True,
        stable_sink_idempotency=True,
    )
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(
            dsn="postgresql://example",
            continuity_policy=fenced_policy,
        )
    )
    with pytest.raises(RuntimeError, match="not production eligible"):
        require_evidence_resource_lock(lock, production=True)


@pytest.mark.parametrize(
    "connection",
    [
        _FakeConn(readback_backend_pid=99),
        _FakeConn(cancel_readback=True),
        _FakeConn(evaluated_at=_NOW - timedelta(seconds=1)),
    ],
)
def test_evidenced_acquisition_rejects_session_substitution_or_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    connection: _FakeConn,
) -> None:
    async def _connect(*_args: object, **_kwargs: object) -> _FakeConn:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://example")
    )

    async def _use() -> None:
        held = None
        with pytest.raises(ResourceLockReleaseUnknownError):
            async with lock.acquire_evidenced(_request()) as held:
                if connection.cancel_readback:
                    with pytest.raises(asyncio.CancelledError):
                        await held.assess_ownership()
                elif connection.evaluated_at < _NOW:
                    with pytest.raises(ResourceLockOwnershipUnknownError):
                        await held.assess_ownership()
                else:
                    assert (await held.assess_ownership()).eligible is False
                with pytest.raises(RuntimeError, match="no longer active"):
                    held.require_active()
        assert held is not None
        assert held.release_receipt is not None
        assert held.release_receipt.state is ResourceLockReleaseState.UNKNOWN

    asyncio.run(_use())


def test_evidenced_acquisition_fails_when_release_is_not_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(released=False)

    async def _connect(*_args: object, **_kwargs: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://example")
    )

    async def _use() -> None:
        held = None
        with pytest.raises(ResourceLockReleaseUnknownError):
            async with lock.acquire_evidenced(_request()) as held:
                pass
        assert held is not None
        assert held.release_receipt is not None
        assert held.release_receipt.state is ResourceLockReleaseState.LOST

    asyncio.run(_use())


def test_evidenced_acquisition_preserves_propagating_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConn(cancel_readback=True)

    async def _connect(*_args: object, **_kwargs: object) -> _FakeConn:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://example")
    )
    captured = []

    async def _use() -> None:
        async with lock.acquire_evidenced(_request()) as held:
            captured.append(held)
            await held.assess_ownership()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_use())
    assert len(captured) == 1
    assert captured[0].release_receipt is not None
    assert captured[0].release_receipt.state is ResourceLockReleaseState.UNKNOWN


def test_evidenced_acquisition_preserves_body_cancellation_when_release_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConn(released=False)

    async def _connect(*_args: object, **_kwargs: object) -> _FakeConn:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://example")
    )
    captured = []

    async def _use() -> None:
        async with lock.acquire_evidenced(_request()) as held:
            captured.append(held)
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_use())
    assert len(captured) == 1
    assert captured[0].release_receipt is not None
    assert captured[0].release_receipt.state is ResourceLockReleaseState.LOST


@pytest.mark.asyncio
async def test_live_postgres_evidenced_session_readback_and_reacquisition() -> None:
    dsn = os.environ.get("FDAI_TEST_RESOURCE_LOCK_DSN", "").strip()
    if not dsn:
        pytest.skip("FDAI_TEST_RESOURCE_LOCK_DSN is not configured")
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(
            dsn=dsn,
            continuity_policy=_policy(),
        )
    )
    request = ResourceLockAcquisitionRequest.create(
        target_ref=f"resource/live-{os.getpid()}",
        action_digest="sha256:" + "1" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "a" * 40,
    )

    async with lock.acquire_evidenced(request) as first:
        first_assessment = await first.assess_ownership()
        assert first_assessment.eligible is True
        first_session = first.acquisition_receipt.session_identity
    with pytest.raises(RuntimeError, match="no longer active"):
        first.require_active()
    assert first.release_receipt is not None
    assert first.release_receipt.state is ResourceLockReleaseState.RELEASED

    async with lock.acquire_evidenced(request) as second:
        second_assessment = await second.assess_ownership()
        assert second_assessment.eligible is True
        assert second.acquisition_receipt.session_identity != first_session
