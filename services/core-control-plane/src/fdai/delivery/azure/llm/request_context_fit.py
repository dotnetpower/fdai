"""Fit bounded conversation context into one model request's declared token budget.

The request keeps the operator's current utterance, the complete capability set,
and the schema; only prior-turn context yields when the whole request would exceed
its prompt profile's request budget. The newest context is kept first, and the
oldest kept item may be shortened from its end, so a follow-up still sees the turn
it continues. The omission is logged with counts only, never content.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from fdai.core.prompts import estimate_chat_request_tokens
from fdai.delivery.azure.llm.model_trace import prepare_model_messages

_LOGGER = logging.getLogger(__name__)
_MIN_KEPT_CHARS = 64


def fit_context_to_budget(
    context: tuple[str, ...],
    *,
    encode: Callable[[tuple[str, ...]], str],
    system_prompt: str,
    response_format: Mapping[str, Any],
    reserved_output_tokens: int,
    budget: int | None,
    call_kind: str,
) -> tuple[str, ...]:
    """Return the newest context whose complete request fits ``budget``."""

    def fits(candidate: tuple[str, ...]) -> bool:
        messages = prepare_model_messages(
            (
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": encode(candidate)},
            )
        ).messages
        estimate = estimate_chat_request_tokens(
            messages=list(messages),
            response_format=response_format,
            reserved_output_tokens=reserved_output_tokens,
        )
        return estimate <= budget if budget is not None else True

    if budget is None or not context or fits(context):
        return context
    kept = context
    while kept and not fits(kept):
        kept = kept[1:]
    fitted = kept
    if len(kept) < len(context):
        # Shorten the newest omitted item into the remaining room instead of losing it.
        dropped = context[len(context) - len(kept) - 1]
        low, high = 0, len(dropped)
        while low < high:
            middle = (low + high + 1) // 2
            if fits((dropped[:middle], *kept)):
                low = middle
            else:
                high = middle - 1
        if low >= _MIN_KEPT_CHARS:
            fitted = (dropped[:low], *kept)
    _LOGGER.info(
        "model_request_context_fitted",
        extra={
            "call_kind": call_kind,
            "context_items": len(context),
            "kept_items": len(fitted),
            "shortened": len(fitted) > len(kept),
        },
    )
    return fitted


__all__ = ["fit_context_to_budget"]
