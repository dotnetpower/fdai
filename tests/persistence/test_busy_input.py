"""Live PostgreSQL busy-input durability and concurrency tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.conversation import (
    BusyInput,
    BusyInputConflictError,
    BusyInputDisposition,
    BusyInputKind,
    BusyInputMode,
    BusyInputStore,
    BusyPendingStatus,
)
from fdai.delivery.persistence import (
    PostgresBusyInputStore,
    PostgresBusyInputStoreConfig,
)

_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 20, 13, tzinfo=UTC)


def test_postgres_busy_input_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresBusyInputStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresBusyInputStoreConfig(dsn="postgresql://example", statement_timeout_ms=0)


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    result = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _store(dsn: str) -> BusyInputStore:
    store = PostgresBusyInputStore(config=PostgresBusyInputStoreConfig(dsn=dsn))
    protocol_store: BusyInputStore = store
    return protocol_store


def _session() -> str:
    return f"busy-session-{uuid.uuid4().hex}"


def _input(
    session_id: str,
    owner: str,
    index: int,
    *,
    expires_at: datetime | None = None,
) -> BusyInput:
    return BusyInput(
        input_id=f"input-{index}",
        idempotency_key=f"idempotency-{index}",
        session_id=session_id,
        principal_id=owner,
        content=f"follow up {index}",
        kind=BusyInputKind.PROSE,
        received_at=_NOW,
        expires_at=expires_at or _NOW + timedelta(minutes=5),
    )


@pytest.mark.integration
async def test_concurrent_duplicate_submit_and_restart_round_trip() -> None:
    dsn = _dsn()
    _upgrade()
    session_id = _session()
    owner = "busy-owner-duplicate"
    first_store = _store(dsn)
    await first_store.create(session_id=session_id, owner_principal_id=owner)
    with pytest.raises(BusyInputConflictError, match="owned by another principal"):
        await first_store.create(
            session_id=session_id,
            owner_principal_id="another-owner",
        )
    incoming = _input(session_id, owner, 1)

    first, second = await asyncio.gather(
        first_store.submit(incoming, now=_NOW),
        first_store.submit(incoming, now=_NOW),
    )

    restarted = _store(dsn)
    state = await restarted.get(session_id, principal_id=owner)
    pending = await restarted.list_pending(session_id, principal_id=owner)
    assert sorted([first.duplicate, second.duplicate]) == [False, True]
    assert first.record == second.record
    assert state is not None and state.next_sequence == 1
    assert pending == (first.record,)


@pytest.mark.integration
async def test_simultaneous_steer_and_finish_never_loses_accepted_input() -> None:
    dsn = _dsn()
    _upgrade()
    session_id = _session()
    owner = "busy-owner-race"
    submit_store = _store(dsn)
    finish_store = _store(dsn)
    created, _ = await submit_store.create(
        session_id=session_id,
        owner_principal_id=owner,
        mode=BusyInputMode.STEER,
    )
    await submit_store.set_active_turn(
        session_id,
        principal_id=owner,
        turn_id="turn-race",
        mode=BusyInputMode.STEER,
        expected_revision=created.revision,
    )

    decision, _ = await asyncio.gather(
        submit_store.submit(_input(session_id, owner, 1), now=_NOW),
        finish_store.finish_turn(session_id, principal_id=owner, turn_id="turn-race"),
    )

    pending = await _store(dsn).list_pending(session_id, principal_id=owner)
    assert len(pending) == 1
    assert pending[0].input == decision.record.input
    assert pending[0].disposition is BusyInputDisposition.QUEUED


@pytest.mark.integration
async def test_overflow_rejection_preserves_all_prior_rows() -> None:
    dsn = _dsn()
    _upgrade()
    session_id = _session()
    owner = "busy-owner-overflow"
    store = _store(dsn)
    await store.create(session_id=session_id, owner_principal_id=owner)
    for index in range(32):
        await store.submit(_input(session_id, owner, index), now=_NOW)

    rejected = await store.submit(_input(session_id, owner, 33), now=_NOW)
    replayed = await _store(dsn).submit(_input(session_id, owner, 33), now=_NOW)
    pending = await store.list_pending(session_id, principal_id=owner)

    assert rejected.reason == "queue_capacity_exceeded"
    assert rejected.record.status is BusyPendingStatus.REJECTED
    assert replayed.duplicate is True
    assert replayed.record == rejected.record
    assert [item.sequence for item in pending] == list(range(32))


@pytest.mark.integration
async def test_consumption_rechecks_current_principal_and_is_exactly_once() -> None:
    dsn = _dsn()
    _upgrade()
    session_id = _session()
    owner = "busy-owner-auth"
    store = _store(dsn)
    await store.create(session_id=session_id, owner_principal_id=owner)
    rejected = await store.submit(_input(session_id, "another-owner", 9), now=_NOW)
    accepted = await store.submit(_input(session_id, owner, 1), now=_NOW)

    assert rejected.record.status is BusyPendingStatus.REJECTED
    assert rejected.record.sequence == accepted.record.sequence == 0
    assert await store.get(session_id, principal_id="another-owner") is None
    with pytest.raises(PermissionError, match="principal mismatch"):
        await store.consume(
            session_id,
            sequence=accepted.record.sequence,
            principal_id="another-owner",
            at=_NOW + timedelta(seconds=1),
        )
    _, consumed = await store.consume(
        session_id,
        sequence=accepted.record.sequence,
        principal_id=owner,
        at=_NOW + timedelta(seconds=1),
    )
    assert consumed.status is BusyPendingStatus.CONSUMED
    with pytest.raises(LookupError, match="was not found"):
        await store.consume(
            session_id,
            sequence=accepted.record.sequence,
            principal_id=owner,
            at=_NOW + timedelta(seconds=2),
        )


@pytest.mark.integration
async def test_expiry_preserves_idempotent_history_after_restart() -> None:
    dsn = _dsn()
    _upgrade()
    session_id = _session()
    owner = "busy-owner-expiry"
    store = _store(dsn)
    await store.create(session_id=session_id, owner_principal_id=owner)
    incoming = _input(
        session_id,
        owner,
        1,
        expires_at=_NOW + timedelta(seconds=1),
    )
    await store.submit(incoming, now=_NOW)

    expired = await store.expire_pending(now=_NOW + timedelta(seconds=2), limit=100)
    restarted = _store(dsn)
    replayed = await restarted.submit(incoming, now=_NOW + timedelta(seconds=3))

    matching = [record for record in expired if record.input.session_id == session_id]
    assert len(matching) == 1
    assert matching[0].status is BusyPendingStatus.EXPIRED
    assert replayed.duplicate is True
    assert replayed.record.status is BusyPendingStatus.EXPIRED
    assert await restarted.list_pending(session_id, principal_id=owner) == ()


@pytest.mark.integration
async def test_mode_preference_survives_store_restart() -> None:
    dsn = _dsn()
    _upgrade()
    session_id = _session()
    owner = "busy-owner-mode"
    store = _store(dsn)
    await store.create(session_id=session_id, owner_principal_id=owner)
    await store.set_mode(
        session_id,
        principal_id=owner,
        mode=BusyInputMode.STEER,
    )

    restarted = _store(dsn)
    state = await restarted.get(session_id, principal_id=owner)

    assert state is not None
    assert state.mode is BusyInputMode.STEER
