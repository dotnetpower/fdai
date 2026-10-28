"""Tests for :mod:`fdai.core.metering.observed`."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from fdai.core.metering.observed import ObservedMeteringStore
from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.sink import InMemoryMeteringSink
from fdai.core.metering.usage import TokenUsage


def _inv() -> LlmInvocation:
    return LlmInvocation(
        occurred_at=datetime(2026, 7, 10, 12, tzinfo=UTC),
        correlation_id="conv-1",
        capability_id="t2.judge",
        model_key="gpt-test",
        tier="T2",
        mode=InvocationMode.ENFORCE,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
    )


class _Observer:
    def __init__(self, *, fail: bool = False) -> None:
        self.seen: list[LlmInvocation] = []
        self._fail = fail

    async def record(self, invocation: LlmInvocation) -> None:
        self.seen.append(invocation)
        if self._fail:
            raise RuntimeError("observer down")


class _FailingPrimary(InMemoryMeteringSink):
    async def record(self, invocation: LlmInvocation) -> None:
        raise RuntimeError("primary down")


async def test_record_writes_primary_and_mirrors_to_observers() -> None:
    primary, observer = InMemoryMeteringSink(), _Observer()
    store = ObservedMeteringStore(primary, (observer,))

    await store.record(_inv())

    assert await store.invocations() == (_inv(),)
    assert observer.seen == [_inv()]


async def test_observer_failure_is_logged_and_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary, healthy = InMemoryMeteringSink(), _Observer()
    store = ObservedMeteringStore(primary, (_Observer(fail=True), healthy))

    with caplog.at_level(logging.WARNING):
        await store.record(_inv())

    assert len(primary) == 1
    assert healthy.seen == [_inv()]
    assert "metering_observer_failed" in caplog.text


async def test_primary_failure_propagates_but_observers_still_see_the_call() -> None:
    observer = _Observer()
    store = ObservedMeteringStore(_FailingPrimary(), (observer,))

    with pytest.raises(RuntimeError, match="primary down"):
        await store.record(_inv())

    assert observer.seen == [_inv()]
