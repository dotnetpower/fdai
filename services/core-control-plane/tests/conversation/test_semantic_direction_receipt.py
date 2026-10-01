"""A directional turn records what its readers cost, split by reader count."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fdai.core.conversation import turn_reservations
from fdai.core.conversation.semantic_direction_receipt import direction_cost_receipt
from fdai.core.conversation.turn_reservations import (
    ReservationPlan,
    TurnReservationLedger,
    plan_capacity,
)

from tests.conversation.test_semantic_reasoning_shadow import _Model, _quoted_form, _run

_VMS = {"m2": ["value:compute.vm", "group:compute.vm"]}


class _ReservingDirections(_Model):
    """Reserve and reconcile each direction call through the ledger, as the adapter does."""

    async def check_direction(self, **kwargs: Any) -> dict[str, Any] | None:
        record = turn_reservations.reserve_call(
            "semantic-direction-check", input_bytes=500, output_tokens=64
        )
        turn_reservations.reconcile_call(record, {"completion_tokens": 7})
        return await super().check_direction(**kwargs)


@pytest.mark.parametrize(
    ("direction", "tiebreak", "readers", "calls"),
    [("agree", "agree", 1, 1), ("disagree", "disagree", 2, 2), ("disagree", "agree", 2, 2)],
)
async def test_a_directional_turn_records_its_reader_count_and_usage(
    direction: str, tiebreak: str, readers: int, calls: int, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="fdai.core.conversation.semantic_direction_receipt")
    model = _ReservingDirections([_quoted_form()], _VMS, direction=direction, tiebreak=tiebreak)

    observation = await _run(model)

    cost = observation.direction_cost
    assert cost is not None
    assert (cost.readers, cost.calls, cost.input_bytes, cost.output_tokens) == (
        readers,
        calls,
        500 * calls,
        7 * calls,
    )
    (record,) = [item for item in caplog.records if item.message == "semantic_direction_cost"]
    assert record.readers == readers  # type: ignore[attr-defined]


def test_a_turn_without_a_direction_reader_records_no_cost() -> None:
    ledger = TurnReservationLedger(plan_capacity(ReservationPlan(())), ReservationPlan(()))

    assert direction_cost_receipt(ledger, tiebreak_calls=0) is None


def test_the_receipt_measures_a_span_counts_settled_usage_and_sent_tiebreaks() -> None:
    from fdai.core.conversation.turn_reservations import PlannedStage, StageCost, TurnStage

    times = [0.0]

    def clock() -> float:
        return times[-1]

    plan = ReservationPlan(
        (PlannedStage(TurnStage.DIRECTION_READER, StageCost(1, 10, 10, 20.0), max_calls=4),)
    )
    ledger = TurnReservationLedger(plan_capacity(plan), plan, clock=clock)
    first = ledger.reserve(TurnStage.DIRECTION_READER, StageCost(1, 5, 5))
    second = ledger.reserve(TurnStage.DIRECTION_READER, StageCost(1, 5, 5))
    # Two concurrent first readers: one from 0 to 2 seconds, the other from 0 to 3.
    times.append(2.0)
    ledger.reconcile(first, output_tokens=3)
    times.append(3.0)
    ledger.reconcile(second, output_tokens=4)
    failed = ledger.reserve(TurnStage.DIRECTION_READER, StageCost(1, 5, 5))
    ledger.fail(failed)

    receipt = direction_cost_receipt(ledger, 2, 1)

    assert receipt is not None
    assert receipt.wall_ms == 3000  # The span, not the 5 seconds the calls add up to.
    assert (receipt.output_tokens, receipt.input_bytes) == (7, 10)
    assert (receipt.calls, receipt.unsettled_calls) == (3, 1)
    # Two first readers and one tie-break attempt that never reserved a call.
    assert direction_cost_receipt(ledger, 3, 1) is not None
    assert direction_cost_receipt(ledger, 4, 1).readers == 1  # type: ignore[union-attr]


def test_the_receipt_uses_actual_usage_when_a_reader_overruns() -> None:
    from fdai.core.conversation.turn_reservations import PlannedStage, StageCost, TurnStage

    times = [0.0]
    plan = ReservationPlan(
        (PlannedStage(TurnStage.DIRECTION_READER, StageCost(1, 10, 5, 1.0), max_calls=1),)
    )
    ledger = TurnReservationLedger(plan_capacity(plan), plan, clock=lambda: times[-1])
    record = ledger.reserve(TurnStage.DIRECTION_READER, StageCost(1, 4, 3))
    times.append(2.0)
    ledger.reconcile(record, output_tokens=8)

    receipt = direction_cost_receipt(ledger, direction_calls=1)

    assert receipt is not None
    assert (receipt.input_bytes, receipt.output_tokens, receipt.wall_ms) == (4, 8, 2000)


def test_a_failover_first_call_counts_as_one_reader() -> None:
    from fdai.core.conversation.turn_reservations import PlannedStage, StageCost, TurnStage

    plan = ReservationPlan(
        (PlannedStage(TurnStage.DIRECTION_READER, StageCost(1, 10, 5), max_calls=1),)
    )
    ledger = TurnReservationLedger(plan_capacity(plan), plan)
    record = ledger.reserve(TurnStage.DIRECTION_READER, StageCost(1, 4, 3))
    ledger.reconcile(record, output_tokens=2)

    receipt = direction_cost_receipt(ledger, direction_calls=1, tiebreak_calls=1)

    assert receipt is not None
    assert receipt.readers == 1


def test_a_failed_first_call_remains_inside_the_reader_wall_span() -> None:
    from fdai.core.conversation.turn_reservations import PlannedStage, StageCost, TurnStage

    times = [0.0]
    plan = ReservationPlan(
        (PlannedStage(TurnStage.DIRECTION_READER, StageCost(1, 10, 5, 5.0), max_calls=2),)
    )
    ledger = TurnReservationLedger(plan_capacity(plan), plan, clock=lambda: times[-1])
    failed = ledger.reserve(TurnStage.DIRECTION_READER, StageCost(1, 4, 3))
    times.append(2.0)
    ledger.fail(failed)
    replacement = ledger.reserve(TurnStage.DIRECTION_READER, StageCost(1, 4, 3))
    times.append(5.0)
    ledger.reconcile(replacement, output_tokens=2)

    receipt = direction_cost_receipt(ledger, direction_calls=2)

    assert receipt is not None
    assert (receipt.readers, receipt.wall_ms, receipt.unsettled_calls) == (1, 5000, 1)
