"""Content-free token budget and provider-usage metrics for conversation model calls."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.prompts import estimate_chat_request_tokens
from fdai.shared.telemetry.metrics import get_meter

_METER = get_meter("fdai.conversation.tokens")
_REQUEST_TOKENS = _METER.create_histogram(
    "fdai.conversation.request.tokens",
    unit="tokens",
    description="Estimated tokens reserved for one conversation model request.",
)
_BUDGET_EXCEEDED = _METER.create_counter(
    "fdai.prompt.token_budget.exceeded",
    unit="requests",
    description="Conversation model requests held before provider I/O by token budget.",
)
_CONTEXT_ITEMS_OMITTED = _METER.create_counter(
    "fdai.conversation.context.items_omitted",
    unit="items",
    description="Prior-turn context items omitted to fit a model request budget.",
)
_PROVIDER_TOKENS = _METER.create_histogram(
    "fdai.conversation.provider.tokens",
    unit="tokens",
    description="Provider-reported conversation tokens by token kind.",
)
_ASSEMBLY_FALLBACK = _METER.create_counter(
    "fdai.prompt.assembly.fallback",
    unit="requests",
    description="Dynamic prompt selections retried with the complete prompt.",
)


def record_request_tokens(
    *,
    call_kind: str,
    estimate: int,
    budget: int | None,
    exceeded: bool,
) -> None:
    """Record one bounded pre-provider request estimate."""

    attributes = {"call_kind": call_kind, "outcome": "held" if exceeded else "prepared"}
    _REQUEST_TOKENS.record(estimate, attributes=attributes)
    if exceeded:
        _BUDGET_EXCEEDED.add(1, attributes={"call_kind": call_kind})
    if budget is not None:
        _REQUEST_TOKENS.record(
            budget,
            attributes={"call_kind": call_kind, "outcome": "budget"},
        )


def estimate_and_record_request_tokens(
    *,
    call_kind: str,
    messages: Sequence[Mapping[str, object]],
    response_format: Mapping[str, object],
    reserved_output_tokens: int,
    models: Sequence[str],
    budget: int | None,
) -> tuple[int, bool]:
    """Estimate the strictest candidate request and record its budget outcome."""

    if not models:
        raise ValueError("at least one model is required for request token estimation")
    estimate = max(
        estimate_chat_request_tokens(
            messages=messages,
            response_format=response_format,
            reserved_output_tokens=reserved_output_tokens,
            model=model,
        )
        for model in models
    )
    exceeded = budget is not None and estimate > budget
    record_request_tokens(
        call_kind=call_kind,
        estimate=estimate,
        budget=budget,
        exceeded=exceeded,
    )
    return estimate, exceeded


def record_context_fit(
    *,
    call_kind: str,
    source_items: int,
    kept_items: int,
    shortened: bool,
) -> None:
    """Record content-free prior-turn omission accounting."""

    omitted = max(source_items - kept_items, 0)
    if omitted:
        _CONTEXT_ITEMS_OMITTED.add(
            omitted,
            attributes={
                "call_kind": call_kind,
                "shortened": "true" if shortened else "false",
            },
        )


def record_assembly_fallback(*, stage: str) -> None:
    """Record one coverage-guard retry with the complete prompt."""

    _ASSEMBLY_FALLBACK.add(1, attributes={"stage": stage})


def record_provider_usage(*, call_kind: str, usage: Mapping[str, Any] | None) -> None:
    """Record bounded provider token counters without retaining model content."""

    if usage is None:
        return
    for token_kind in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
        value = usage.get(token_kind)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            _PROVIDER_TOKENS.record(
                value,
                attributes={"call_kind": call_kind, "token_kind": token_kind},
            )


__all__ = [
    "estimate_and_record_request_tokens",
    "record_assembly_fallback",
    "record_context_fit",
    "record_provider_usage",
    "record_request_tokens",
]
