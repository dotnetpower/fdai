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
    """One turn's direction readers: how many ran, and what their calls used."""

    readers: int
    calls: int
    input_bytes: int
    output_tokens: int
    wall_ms: int


def direction_cost_receipt(
    ledger: TurnReservationLedger, *, tiebreak_calls: int
) -> DirectionCostReceipt | None:
    """Return the turn's direction cost, or ``None`` when no direction reader ran."""

    records = [item for item in ledger.records if item.stage is TurnStage.DIRECTION_READER]
    if not records:
        return None
    receipt = DirectionCostReceipt(
        readers=2 if tiebreak_calls else 1,
        calls=len(records),
        input_bytes=sum(item.charged.input_bytes for item in records),
        output_tokens=sum(item.charged.output_tokens for item in records),
        wall_ms=int(sum(item.charged.wall_seconds for item in records) * 1000),
    )
    _LOGGER.info(
        "semantic_direction_cost",
        extra={
            "readers": receipt.readers,
            "calls": receipt.calls,
            "input_bytes": receipt.input_bytes,
            "output_tokens": receipt.output_tokens,
            "wall_ms": receipt.wall_ms,
        },
    )
    return receipt


__all__ = ["DirectionCostReceipt", "direction_cost_receipt"]
