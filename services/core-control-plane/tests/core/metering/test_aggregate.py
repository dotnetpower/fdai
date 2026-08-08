"""Tests for :mod:`fdai.core.metering.aggregate`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fdai.core.metering.aggregate import (
    summaries_as_mapping,
    summarize_by_conversation,
    summarize_by_day,
    summarize_by_month,
    summarize_total,
)
from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.usage import TokenUsage

_UTC = UTC


def _inv(
    *,
    when: datetime,
    corr: str,
    prompt: int,
    completion: int,
    cost: Decimal | None,
) -> LlmInvocation:
    return LlmInvocation(
        occurred_at=when,
        correlation_id=corr,
        capability_id="t2.reasoner.primary",
        model_key="gpt-4o",
        tier="T2",
        mode=InvocationMode.ENFORCE,
        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion),
        cost=cost,
    )


_RECORDS = [
    _inv(
        when=datetime(2026, 7, 9, 10, tzinfo=_UTC),
        corr="evt-a",
        prompt=1000,
        completion=200,
        cost=Decimal("0.30"),
    ),
    _inv(
        when=datetime(2026, 7, 9, 11, tzinfo=_UTC),
        corr="evt-a",
        prompt=500,
        completion=100,
        cost=Decimal("0.20"),
    ),
    _inv(
        when=datetime(2026, 7, 10, 9, tzinfo=_UTC),
        corr="evt-b",
        prompt=800,
        completion=50,
        cost=None,  # unpriced model
    ),
]


def test_by_conversation_rolls_up_and_sorts() -> None:
    summaries = summarize_by_conversation(_RECORDS)
    assert [s.key for s in summaries] == ["evt-a", "evt-b"]
    a = summaries[0]
    assert a.invocations == 2
    assert a.priced_invocations == 2
    assert a.usage.total_tokens == 1800
    assert a.cost == Decimal("0.50")
    assert a.has_unpriced is False


def test_unpriced_group_is_transparent() -> None:
    b = summarize_by_conversation(_RECORDS)[1]
    assert b.invocations == 1
    assert b.priced_invocations == 0
    assert b.cost == Decimal("0")
    assert b.has_unpriced is True


def test_by_day_and_month_bucketing() -> None:
    days = summarize_by_day(_RECORDS)
    assert [s.key for s in days] == ["2026-07-09", "2026-07-10"]
    assert days[0].cost == Decimal("0.50")

    months = summarize_by_month(_RECORDS)
    assert [s.key for s in months] == ["2026-07"]
    assert months[0].invocations == 3
    assert months[0].usage.total_tokens == 2650


def test_total_summary() -> None:
    total = summarize_total(_RECORDS)
    assert total.key == "total"
    assert total.invocations == 3
    assert total.priced_invocations == 2
    assert total.cost == Decimal("0.50")


def test_empty_records() -> None:
    assert summarize_by_day([]) == ()
    total = summarize_total([])
    assert total.invocations == 0
    assert total.cost == Decimal("0")


def test_summaries_as_mapping_serialises_cost_as_str() -> None:
    rows = summaries_as_mapping(summarize_by_conversation(_RECORDS))
    assert rows[0]["cost"] == "0.50"
    assert rows[0]["total_tokens"] == 1800
    assert rows[1]["has_unpriced"] is True


def _priced(corr: str, cost: str, currency: str, mode: InvocationMode) -> LlmInvocation:
    return LlmInvocation(
        occurred_at=datetime(2026, 7, 10, 9, tzinfo=_UTC),
        correlation_id=corr,
        capability_id="t2.reasoner.primary",
        model_key="gpt-4o",
        tier="T2",
        mode=mode,
        usage=TokenUsage(prompt_tokens=100, completion_tokens=10),
        cost=Decimal(cost),
        currency=currency,
    )


def test_single_currency_surfaced() -> None:
    recs = [_priced("e1", "1.0", "USD", InvocationMode.ENFORCE)]
    total = summarize_total(recs)
    assert total.currency == "USD"
    assert total.has_mixed_currency is False


def test_mixed_currency_flagged() -> None:
    recs = [
        _priced("e1", "1.0", "USD", InvocationMode.ENFORCE),
        _priced("e1", "1.0", "EUR", InvocationMode.ENFORCE),
    ]
    total = summarize_total(recs)
    assert total.currency == "mixed"
    assert total.has_mixed_currency is True
    row = summaries_as_mapping([total])[0]
    assert row["has_mixed_currency"] is True


def test_summarize_by_mode_splits_shadow_and_enforce() -> None:
    from fdai.core.metering.aggregate import summarize_by_mode

    recs = [
        _priced("e1", "1.0", "USD", InvocationMode.ENFORCE),
        _priced("e2", "0.5", "USD", InvocationMode.SHADOW),
        _priced("e3", "0.25", "USD", InvocationMode.SHADOW),
    ]
    by_mode = summarize_by_mode(recs)
    modes = {s.key: s for s in by_mode}
    assert modes["enforce"].cost == Decimal("1.0")
    assert modes["shadow"].cost == Decimal("0.75")
    assert modes["shadow"].invocations == 2


def test_cost_precision_is_capped() -> None:
    # A pathologically long decimal is capped to 6 fractional digits on
    # render, while short values pass through unchanged.
    long_cost = _priced("e1", "0.12345678901234", "USD", InvocationMode.ENFORCE)
    row = summaries_as_mapping([summarize_total([long_cost])])[0]
    assert row["cost"] == "0.123457"

    short = _priced("e2", "0.50", "USD", InvocationMode.ENFORCE)
    short_row = summaries_as_mapping([summarize_total([short])])[0]
    assert short_row["cost"] == "0.50"
