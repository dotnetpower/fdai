"""Tests for :mod:`fdai.core.metering.sink`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.sink import InMemoryMeteringSink, MeteringReader, MeteringSink
from fdai.core.metering.usage import TokenUsage


def _inv(corr: str) -> LlmInvocation:
    return LlmInvocation(
        occurred_at=datetime(2026, 7, 10, 12, tzinfo=UTC),
        correlation_id=corr,
        capability_id="t1.judge",
        model_key="gpt-4o-mini",
        tier="T1",
        mode=InvocationMode.SHADOW,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        cost=Decimal("0.001"),
    )


async def test_record_then_read_roundtrip() -> None:
    sink = InMemoryMeteringSink()
    await sink.record(_inv("evt-1"))
    await sink.record(_inv("evt-2"))
    records = await sink.invocations()
    assert len(sink) == 2
    assert [r.correlation_id for r in records] == ["evt-1", "evt-2"]


def test_in_memory_sink_satisfies_protocols() -> None:
    sink = InMemoryMeteringSink()
    assert isinstance(sink, MeteringSink)
    assert isinstance(sink, MeteringReader)


async def test_bounded_ring_evicts_oldest() -> None:
    sink = InMemoryMeteringSink(max_records=2)
    for i in range(4):
        await sink.record(_inv(f"evt-{i}"))
    records = await sink.invocations()
    assert len(sink) == 2
    # Oldest two evicted; newest two retained in order.
    assert [r.correlation_id for r in records] == ["evt-2", "evt-3"]


async def test_unbounded_when_max_records_none() -> None:
    sink = InMemoryMeteringSink(max_records=None)
    for i in range(1000):
        await sink.record(_inv(f"evt-{i}"))
    assert len(sink) == 1000


def test_rejects_non_positive_max_records() -> None:
    with pytest.raises(ValueError, match="max_records"):
        InMemoryMeteringSink(max_records=0)
