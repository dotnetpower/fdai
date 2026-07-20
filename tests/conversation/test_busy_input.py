from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.conversation.busy_input import (
    BusyInput,
    BusyInputDisposition,
    BusyInputKind,
    BusyInputMode,
    BusyPendingStatus,
    BusySessionState,
    arbitrate_busy_input,
    consume_pending_input,
    finish_active_turn,
)

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _input(index: int, *, kind: BusyInputKind = BusyInputKind.PROSE) -> BusyInput:
    return BusyInput(
        input_id=f"input-{index}",
        idempotency_key=f"idempotency-{index}",
        session_id="session-one",
        principal_id="operator-one",
        content=f"follow up {index}",
        kind=kind,
        received_at=_NOW,
        expires_at=_NOW + timedelta(minutes=5),
    )


def _state(mode: BusyInputMode, *, active: bool = True) -> BusySessionState:
    return BusySessionState(
        session_id="session-one",
        owner_principal_id="operator-one",
        mode=mode,
        revision=1,
        next_sequence=0,
        active_turn_id="turn-one" if active else None,
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (BusyInputMode.QUEUE, BusyInputDisposition.QUEUED),
        (BusyInputMode.INTERRUPT, BusyInputDisposition.INTERRUPTING),
        (BusyInputMode.STEER, BusyInputDisposition.STEERED),
    ],
)
def test_busy_modes_assign_one_durable_disposition(
    mode: BusyInputMode,
    expected: BusyInputDisposition,
) -> None:
    decision = arbitrate_busy_input(_state(mode), _input(1), now=_NOW)

    assert decision.record.disposition is expected
    assert decision.state.pending == (decision.record,)
    assert decision.state.next_sequence == 1


def test_duplicate_does_not_allocate_another_sequence() -> None:
    first = arbitrate_busy_input(_state(BusyInputMode.QUEUE), _input(1), now=_NOW)

    duplicate = arbitrate_busy_input(first.state, _input(1), now=_NOW)

    assert duplicate.duplicate is True
    assert duplicate.record == first.record
    assert duplicate.state == first.state


def test_turn_end_atomically_falls_unconsumed_steer_back_to_queue() -> None:
    steered = arbitrate_busy_input(_state(BusyInputMode.STEER), _input(1), now=_NOW)

    finished = finish_active_turn(steered.state, turn_id="turn-one")

    assert finished.active_turn_id is None
    assert finished.pending[0].disposition is BusyInputDisposition.QUEUED
    consumed_state, consumed = consume_pending_input(
        finished,
        sequence=0,
        principal_id="operator-one",
        at=_NOW + timedelta(seconds=1),
    )
    assert consumed.status is BusyPendingStatus.CONSUMED
    with pytest.raises(ValueError, match="not pending"):
        consume_pending_input(
            consumed_state,
            sequence=0,
            principal_id="operator-one",
            at=_NOW + timedelta(seconds=2),
        )


def test_control_input_cannot_be_combined_with_steer_prose() -> None:
    decision = arbitrate_busy_input(
        _state(BusyInputMode.STEER),
        _input(1, kind=BusyInputKind.APPROVAL),
        now=_NOW,
    )

    assert decision.record.disposition is BusyInputDisposition.REJECTED
    assert decision.reason == "control_input_cannot_steer"


def test_control_input_never_interrupts_conversational_backend() -> None:
    decision = arbitrate_busy_input(
        _state(BusyInputMode.INTERRUPT),
        _input(1, kind=BusyInputKind.APPROVAL),
        now=_NOW,
    )

    assert decision.record.disposition is BusyInputDisposition.QUEUED
    assert decision.state.pending == (decision.record,)


def test_capacity_rejection_keeps_all_accepted_inputs() -> None:
    state = _state(BusyInputMode.QUEUE)
    for index in range(32):
        state = arbitrate_busy_input(state, _input(index), now=_NOW).state

    rejected = arbitrate_busy_input(state, _input(33), now=_NOW)

    assert rejected.reason == "queue_capacity_exceeded"
    assert len(rejected.state.pending) == 32
    assert rejected.state == state


def test_consumption_rechecks_authorization() -> None:
    queued = arbitrate_busy_input(_state(BusyInputMode.QUEUE), _input(1), now=_NOW)
    with pytest.raises(PermissionError):
        consume_pending_input(
            queued.state,
            sequence=0,
            principal_id="operator-two",
            at=_NOW,
        )
