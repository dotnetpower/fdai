from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.conversation import (
    BusyInput,
    BusyInputCoordinator,
    BusyInputDisposition,
    BusyInputKind,
    BusyInputMode,
    InMemoryBusyInputStore,
)
from fdai.delivery.read_api.busy_input_runtime import (
    BUSY_INPUT_METRIC_NAMES,
    BusyInputRuntimeMetrics,
)

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _input(index: int) -> BusyInput:
    return BusyInput(
        input_id=f"input-{index}",
        idempotency_key=f"idempotency-{index}",
        session_id="session-one",
        principal_id="operator-one",
        content=f"follow up {index}",
        kind=BusyInputKind.PROSE,
        received_at=_NOW,
        expires_at=_NOW + timedelta(minutes=5),
    )


async def test_interrupt_sets_only_conversation_cancel_event() -> None:
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    active = await coordinator.begin_turn(
        session_id="session-one",
        turn_id="turn-one",
        principal_id="operator-one",
        mode=BusyInputMode.INTERRUPT,
    )

    decision = await coordinator.submit(_input(1), now=_NOW)

    assert decision.record.disposition is BusyInputDisposition.INTERRUPTING
    assert active.cancel_event.is_set()
    assert not active.steer_event.is_set()


async def test_steer_is_consumed_once_at_safe_boundary() -> None:
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    active = await coordinator.begin_turn(
        session_id="session-one",
        turn_id="turn-one",
        principal_id="operator-one",
        mode=BusyInputMode.STEER,
    )
    await coordinator.submit(_input(1), now=_NOW)

    consumed = await coordinator.safe_boundary(
        session_id="session-one",
        principal_id="operator-one",
        at=_NOW + timedelta(seconds=1),
    )
    duplicate = await coordinator.safe_boundary(
        session_id="session-one",
        principal_id="operator-one",
        at=_NOW + timedelta(seconds=2),
    )

    assert consumed is not None and consumed.input.content == "follow up 1"
    assert duplicate is None
    assert not active.steer_event.is_set()


async def test_finish_turn_falls_unconsumed_steer_back_to_queue() -> None:
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    await coordinator.begin_turn(
        session_id="session-one",
        turn_id="turn-one",
        principal_id="operator-one",
        mode=BusyInputMode.STEER,
    )
    await coordinator.submit(_input(1), now=_NOW)

    await coordinator.finish_turn(
        session_id="session-one",
        turn_id="turn-one",
        principal_id="operator-one",
    )
    pending = await coordinator.pending(
        session_id="session-one",
        principal_id="operator-one",
    )

    assert coordinator.active("session-one") is None
    assert pending[0].disposition is BusyInputDisposition.QUEUED


async def test_saved_mode_is_used_by_later_turn_and_cancel_is_owner_scoped() -> None:
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    saved = await coordinator.set_mode(
        session_id="session-one",
        principal_id="operator-one",
        mode=BusyInputMode.INTERRUPT,
    )

    active = await coordinator.begin_turn(
        session_id="session-one",
        turn_id="turn-one",
        principal_id="operator-one",
    )

    assert saved.mode is BusyInputMode.INTERRUPT
    assert (
        await coordinator.cancel_current(
            session_id="session-one",
            principal_id="another-operator",
        )
        is False
    )
    assert not active.cancel_event.is_set()
    assert (
        await coordinator.cancel_current(
            session_id="session-one",
            principal_id="operator-one",
        )
        is True
    )
    assert active.cancel_event.is_set()


async def test_metrics_cover_dispositions_and_recovery_paths() -> None:
    metrics = BusyInputRuntimeMetrics()
    store = InMemoryBusyInputStore()
    coordinator = BusyInputCoordinator(store=store, metrics=metrics)
    await coordinator.begin_turn(
        session_id="session-one",
        turn_id="turn-one",
        principal_id="operator-one",
        mode=BusyInputMode.STEER,
    )
    await coordinator.submit(_input(1), now=_NOW)
    await coordinator.finish_turn(
        session_id="session-one",
        turn_id="turn-one",
        principal_id="operator-one",
    )
    expired = await coordinator.expire_pending(
        now=_NOW + timedelta(minutes=6),
    )
    other_process = BusyInputCoordinator(store=store)
    await other_process.begin_turn(
        session_id="session-two",
        turn_id="turn-two",
        principal_id="operator-one",
        mode=BusyInputMode.INTERRUPT,
    )
    await coordinator.submit(
        BusyInput(
            input_id="input-two",
            idempotency_key="idempotency-two",
            session_id="session-two",
            principal_id="operator-one",
            content="interrupt from another process",
            kind=BusyInputKind.PROSE,
            received_at=_NOW,
            expires_at=_NOW + timedelta(minutes=5),
        ),
        now=_NOW,
    )

    snapshot = metrics.snapshot()
    assert set(snapshot) == set(BUSY_INPUT_METRIC_NAMES)
    assert snapshot["steered"] == 1
    assert snapshot["steer_fallback"] == 1
    assert snapshot["expiry"] == len(expired) == 1
    assert snapshot["race_recovery"] == 1
