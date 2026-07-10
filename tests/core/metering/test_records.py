"""Tests for :mod:`fdai.core.metering.records`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.usage import TokenUsage

_UTC = UTC
_USAGE = TokenUsage(prompt_tokens=100, completion_tokens=20)


def _invocation(**overrides: object) -> LlmInvocation:
    base: dict[str, object] = {
        "occurred_at": datetime(2026, 7, 10, 12, 0, tzinfo=_UTC),
        "correlation_id": "evt-1",
        "capability_id": "t2.reasoner.primary",
        "model_key": "gpt-4o",
        "tier": "T2",
        "mode": InvocationMode.ENFORCE,
        "usage": _USAGE,
        "cost": Decimal("0.5"),
    }
    base.update(overrides)
    return LlmInvocation(**base)  # type: ignore[arg-type]


def test_day_and_month_buckets_use_utc() -> None:
    # 01:30 at +09:00 is the previous UTC day.
    kst = timezone(timedelta(hours=9))
    inv = _invocation(occurred_at=datetime(2026, 7, 10, 1, 30, tzinfo=kst))
    assert inv.day_bucket == "2026-07-09"
    assert inv.month_bucket == "2026-07"


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _invocation(occurred_at=datetime(2026, 7, 10, 12, 0))  # noqa: DTZ001


def test_negative_cost_rejected() -> None:
    with pytest.raises(ValueError, match="cost"):
        _invocation(cost=Decimal("-0.01"))


def test_empty_currency_rejected() -> None:
    with pytest.raises(ValueError, match="currency"):
        _invocation(currency="")


def test_cost_may_be_none() -> None:
    assert _invocation(cost=None).cost is None


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("correlation_id", "", "correlation_id"),
        ("capability_id", "", "capability_id"),
        ("model_key", "", "model_key"),
        ("tier", "", "tier"),
    ],
)
def test_empty_identifier_fields_rejected(field: str, value: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _invocation(**{field: value})
