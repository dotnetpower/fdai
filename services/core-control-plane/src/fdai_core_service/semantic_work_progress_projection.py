"""Project presentation-only work progress into one durable semantic payload.

The fields describe how the turn's work was shaped and measured. They are not evidence, never
enter the evidence digest, and never change the terminal disposition or authority.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime

from fdai.core.conversation.adaptive_service import AdaptiveBudgetTelemetry
from fdai_service_contracts import SemanticTurnRequest
from fdai_service_contracts.semantic_work_progress import (
    TurnBudgetMeasure,
    TurnBudgetTelemetry,
    WorkProgressShape,
    conversation_model_tier_receipt,
)
from pydantic import ValidationError

_LOGGER = logging.getLogger(__name__)


def applied_context_receipts(
    request: SemanticTurnRequest,
    *,
    observed_at: datetime,
) -> tuple[dict[str, object], ...]:
    """Return receipts for operator preferences the runtime applied to this request.

    The per-conversation model tier travels with the request and selects the model-authored
    stages. ``Auto`` is the absence of a preference, so it yields no receipt.
    """

    tier = request.conversation_model_tier
    if tier is None:
        return ()
    return (conversation_model_tier_receipt(tier, observed_at=observed_at).model_dump(mode="json"),)


def work_progress_payload(
    *,
    shape: WorkProgressShape | None,
    turn_budget: AdaptiveBudgetTelemetry | None,
    context_receipts: tuple[dict[str, object], ...],
    as_of: datetime,
) -> Mapping[str, object]:
    """Return the additive payload fields in the wire shape the Console parses."""

    fields: dict[str, object] = {}
    if shape is not None:
        fields["work_progress_shape"] = shape.model_dump(mode="json")
    budget = _turn_budget(turn_budget, as_of=as_of)
    if budget is not None:
        fields["turn_budget"] = budget
    if context_receipts:
        fields["context_receipts"] = list(context_receipts)
    return fields


def _turn_budget(
    telemetry: AdaptiveBudgetTelemetry | None,
    *,
    as_of: datetime,
) -> dict[str, object] | None:
    if telemetry is None:
        return None
    try:
        record = TurnBudgetTelemetry(
            model_calls=TurnBudgetMeasure(
                used=telemetry.calls,
                reserved=0,
                maximum=telemetry.max_calls,
            ),
            tokens=TurnBudgetMeasure(
                used=telemetry.tokens_used,
                reserved=telemetry.tokens_reserved,
                maximum=telemetry.max_tokens,
            ),
            elapsed_ms=TurnBudgetMeasure(
                used=telemetry.elapsed_ms,
                reserved=0,
                maximum=telemetry.max_elapsed_ms,
            ),
            as_of=as_of,
            complete=telemetry.complete,
            exhaustion_reason=telemetry.exhaustion_reason,
        )
    except ValidationError:
        _LOGGER.warning("semantic_turn_budget_unrepresentable")
        return None
    return record.model_dump(mode="json", exclude_none=True)


__all__ = ["applied_context_receipts", "work_progress_payload"]
