"""Record what settling relation directions cost in one turn, by reader count.

A directional turn asks one blind reader per disputed relation, and a second blind reader
of a third family only on a dispute. The receipt splits one-reader from two-reader turns
and carries content-free usage from the turn's reservation ledger, so a sampled window can
report latency and token cost per turn type.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .turn_reservations import TurnReservationLedger, TurnStage

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DirectionCostReceipt:
    """One turn's direction readers: how many ran, and what their settled calls used."""

    readers: int
    calls: int
    input_bytes: int
    output_tokens: int
    wall_ms: int
    unsettled_calls: int = 0


def direction_cost_receipt(
    ledger: TurnReservationLedger, direction_calls: int = 0, tiebreak_calls: int = 0
) -> DirectionCostReceipt | None:
    """Return the turn's direction cost, or ``None`` when no direction reader ran.

    The first readers run concurrently, so latency is the span from the first call's start
    to the last call's end. A call that failed or never reconciled counts as a call but adds
    no usage, and a second reader counts only when a tie-break call was actually sent.
    """

    records = [item for item in ledger.records if item.stage is TurnStage.DIRECTION_READER]
    if not records:
        return None
    settled = [
        item
        for item in records
        if item.status in {"reconciled", "overrun"} and item.actual is not None
    ]
    first_calls = max(direction_calls - tiebreak_calls, 0)
    ended = [item.ended_at for item in records if item.ended_at is not None]
    span = max(ended) - min(item.started for item in records) if ended else 0.0
    receipt = DirectionCostReceipt(
        readers=2 if first_calls and tiebreak_calls and len(records) > first_calls else 1,
        calls=len(records),
        input_bytes=sum(item.actual.input_bytes for item in settled if item.actual is not None),
        output_tokens=sum(item.actual.output_tokens for item in settled if item.actual is not None),
        wall_ms=int(span * 1000),
        unsettled_calls=len(records) - len(settled),
    )
    _LOGGER.info(
        "semantic_direction_cost",
        extra={
            "readers": receipt.readers,
            "calls": receipt.calls,
            "input_bytes": receipt.input_bytes,
            "output_tokens": receipt.output_tokens,
            "wall_ms": receipt.wall_ms,
            "unsettled_calls": receipt.unsettled_calls,
        },
    )
    return receipt


__all__ = ["DirectionCostReceipt", "direction_cost_receipt"]
