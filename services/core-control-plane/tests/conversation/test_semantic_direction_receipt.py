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
