from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.conversation.busy_input import (
    BusyInput,
    BusyInputDisposition,
    BusyInputKind,
    BusyInputMode,
    BusyPendingStatus,
)
from fdai.core.conversation.busy_input_store import (
    BusyInputConflictError,
    BusyInputStore,
    InMemoryBusyInputStore,
)

_NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)
_SESSION = "session-store"
_OWNER = "operator-store"


def _input(index: int, *, expires_at: datetime | None = None) -> BusyInput:
    return BusyInput(
        input_id=f"input-{index}",
        idempotency_key=f"idempotency-{index}",
        session_id=_SESSION,
        principal_id=_OWNER,
        content=f"follow up {index}",
        kind=BusyInputKind.PROSE,
        received_at=_NOW,
        expires_at=expires_at or _NOW + timedelta(minutes=5),
    )


async def _store(*, mode: BusyInputMode = BusyInputMode.QUEUE) -> BusyInputStore:
    store = InMemoryBusyInputStore()
    protocol_store: BusyInputStore = store
    created, is_new = await protocol_store.create(
        session_id=_SESSION,
        owner_principal_id=_OWNER,
        mode=mode,
    )
    assert is_new and created.revision == 1
    return protocol_store


async def test_create_get_and_active_turn_revision_cas_are_owner_scoped() -> None:
    store = await _store()
    assert await store.get(_SESSION, principal_id="another-operator") is None
    with pytest.raises(BusyInputConflictError, match="owned by another principal"):
        await store.create(
            session_id=_SESSION,
            owner_principal_id="another-operator",
        )

    active = await store.set_active_turn(
        _SESSION,
        principal_id=_OWNER,
        turn_id="turn-one",
        mode=BusyInputMode.STEER,
        expected_revision=1,
    )

    assert active.active_turn_id == "turn-one"
    assert active.mode is BusyInputMode.STEER
    with pytest.raises(BusyInputConflictError, match="revision mismatch"):
        await store.set_active_turn(
            _SESSION,
            principal_id=_OWNER,
            turn_id="turn-two",
            mode=BusyInputMode.INTERRUPT,
            expected_revision=1,
        )


async def test_concurrent_duplicate_submit_allocates_one_record() -> None:
    store = await _store()
    incoming = _input(1)

    first, second = await asyncio.gather(
        store.submit(incoming, now=_NOW),
        store.submit(incoming, now=_NOW),
    )

    assert sorted([first.duplicate, second.duplicate]) == [False, True]
    assert first.record == second.record
    assert await store.list_pending(_SESSION, principal_id=_OWNER) == (first.record,)


async def test_simultaneous_steer_and_finish_never_loses_input() -> None:
    store = await _store(mode=BusyInputMode.STEER)
    active = await store.set_active_turn(
        _SESSION,
        principal_id=_OWNER,
        turn_id="turn-one",
        mode=BusyInputMode.STEER,
        expected_revision=1,
    )
    assert active.revision == 2

    decision, finished = await asyncio.gather(
        store.submit(_input(1), now=_NOW),
        store.finish_turn(_SESSION, principal_id=_OWNER, turn_id="turn-one"),
    )
    pending = await store.list_pending(_SESSION, principal_id=_OWNER)

    assert len(pending) == 1
    assert pending[0].input.input_id == decision.record.input.input_id
    assert pending[0].disposition is BusyInputDisposition.QUEUED
    assert finished.active_turn_id is None


async def test_consumption_is_exactly_once_and_rechecks_principal() -> None:
    store = await _store()
    submitted = await store.submit(_input(1), now=_NOW)

    with pytest.raises(PermissionError, match="principal mismatch"):
        await store.consume(
            _SESSION,
            sequence=submitted.record.sequence,
            principal_id="another-operator",
            at=_NOW + timedelta(seconds=1),
        )
    _, consumed = await store.consume(
        _SESSION,
        sequence=submitted.record.sequence,
        principal_id=_OWNER,
        at=_NOW + timedelta(seconds=1),
    )
    assert consumed.status is BusyPendingStatus.CONSUMED
    with pytest.raises(LookupError, match="was not found"):
        await store.consume(
            _SESSION,
            sequence=submitted.record.sequence,
            principal_id=_OWNER,
            at=_NOW + timedelta(seconds=2),
        )


async def test_consumed_history_does_not_reduce_future_pending_capacity() -> None:
    store = await _store()
    for index in range(32):
        submitted = await store.submit(_input(index), now=_NOW)
        await store.consume(
            _SESSION,
            sequence=submitted.record.sequence,
            principal_id=_OWNER,
            at=_NOW + timedelta(seconds=1),
        )

    accepted = await store.submit(_input(33), now=_NOW)

    assert accepted.reason is None
    assert accepted.record.sequence == 32


async def test_overflow_rejects_new_input_and_preserves_prior_rows() -> None:
    store = await _store()
    for index in range(32):
        await store.submit(_input(index), now=_NOW)

    rejected = await store.submit(_input(33), now=_NOW)
    pending = await store.list_pending(_SESSION, principal_id=_OWNER)

    assert rejected.reason == "queue_capacity_exceeded"
    assert rejected.record.status is BusyPendingStatus.REJECTED
    assert len(pending) == 32
    assert [item.sequence for item in pending] == list(range(32))


async def test_expiry_marks_history_without_deleting_it() -> None:
    store = await _store()
    expiring = _input(1, expires_at=_NOW + timedelta(seconds=1))
    submitted = await store.submit(expiring, now=_NOW)

    expired = await store.expire_pending(now=_NOW + timedelta(seconds=2), limit=1)
    duplicate = await store.submit(expiring, now=_NOW + timedelta(seconds=3))

    assert expired[0].status is BusyPendingStatus.EXPIRED
    assert duplicate.duplicate is True
    assert duplicate.record.status is BusyPendingStatus.EXPIRED
    assert submitted.record.input == duplicate.record.input
    assert await store.list_pending(_SESSION, principal_id=_OWNER) == ()


async def test_idempotency_key_reuse_with_changed_payload_fails_closed() -> None:
    store = await _store()
    incoming = _input(1)
    await store.submit(incoming, now=_NOW)

    with pytest.raises(BusyInputConflictError, match="reused"):
        await store.submit(replace(incoming, content="different"), now=_NOW)
